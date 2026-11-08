"""Single-face baseline enrollment and event dispatch."""
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import time
from jsonschema import Draft202012Validator
from .capture import Capture
from .events import person_seen
from .gallery import Gallery, atomic_json
from .recognition import Baseline, decision
from .vision import Vision
from .dataset import file_hash


def segment_id(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = json.loads(path.read_text()) if path.exists() else 0
        if type(value) is not int or value < 0:
            raise ValueError('Invalid persistent segment counter')
        atomic_json(path, value + 1)
        return value


def execute(args):
    vision = Vision(args.detector, args.recognizer)
    gallery = Gallery(args.gallery, vision.signature)
    if args.command == 'remove':
        gallery.remove(args.person_id)
        return
    if args.command == 'enroll' and args.person_id in gallery.people:
        raise ValueError('Already enrolled; remove explicitly before re-enrollment')
    origin = None
    if args.replay_origin:
        origin = datetime.fromisoformat(args.replay_origin.replace('Z', '+00:00'))
        if origin.tzinfo is None or origin.utcoffset().total_seconds() != 0:
            raise ValueError('Replay origin must be UTC')
    producer = None
    if args.command == 'run':
        if not gallery.people:
            raise ValueError('Enroll people first')
        policy = json.loads(args.policy.read_text())
        if policy['gallery'] != gallery.fingerprint or policy['model'] != vision.signature:
            raise ValueError('Policy is incompatible with current gallery/model; recalibrate')
        if not policy.get('development_manifest'):
            raise ValueError('Policy must identify its held-out development manifest')
        accept, reject, margin = (policy[key] for key in ('accept', 'reject', 'margin'))
        decision({person: 0. for person in gallery.people}, accept, reject, margin)
        validator = Draft202012Validator(json.loads(args.schema.read_text()))
        if args.broker:
            from confluent_kafka import Producer
            producer = Producer({'bootstrap.servers': args.broker, 'enable.idempotence': True,
                                 'queue.buffering.max.messages': 10, 'delivery.timeout.ms': 5000})
    engine = Baseline(gallery.scores, policy) if args.command == 'run' else None
    engine_generation = None
    samples = []
    last_sample = -float('inf')
    last_publish = -float('inf')
    track = None
    previous_enrollment_time = None
    previous_decision = None
    previous_segment = None
    try:
        with Capture(args.source, origin) as capture:
            for image, received, timestamp in capture:
                if Gallery(args.gallery, vision.signature).fingerprint != gallery.fingerprint:
                    raise ValueError('Gallery changed; restart and recalibrate before publishing')
                now = time.monotonic()
                if now - received > 1:
                    if engine is not None:
                        engine.reset()
                    samples.clear()
                    previous_enrollment_time = None
                    track = None
                    continue
                observed_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp() if origin else received
                if observed_time - last_sample < .2 - 1e-6:
                    continue
                last_sample = observed_time
                observation = vision.single_face(image)
                if observation is None:
                    if engine is not None:
                        engine.reset()
                    samples.clear()
                    previous_enrollment_time = None
                    track = None
                    continue
                vector, weight = observation
                if args.command == 'enroll':
                    if samples and (observed_time - previous_enrollment_time > 1
                                    or float(samples[-1] @ vector) < .3):
                        samples.clear()
                    previous_enrollment_time = observed_time
                    samples.append(vector)
                    if len(samples) >= 20:
                        gallery.enroll(args.person_id, samples, provenance={
                            'session_id': args.session_id,
                            'path': str(Path(args.source).resolve()) if Path(args.source).is_file() else None,
                            'sha256': file_hash(args.source) if Path(args.source).is_file() else None})
                        print('Enrollment saved locally; no source images retained')
                        return
                    continue
                # Video presentation time, rather than decode speed, governs replay evidence.
                observed_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp() if origin else received
                result = engine.observe(vector, weight, observed_time)
                if result is None:
                    continue
                if track is None or engine_generation != engine.generation:
                    track = segment_id(args.gallery.parent / 'next-track.json')
                    engine_generation = engine.generation
                if (result[0] == previous_decision and track == previous_segment and observed_time - last_publish < .5) or time.monotonic() - received > 1:
                    continue
                person, confidence = result
                event = person_seen(track, person, confidence, ts=timestamp)
                validator.validate(event)
                payload = json.dumps(event, allow_nan=False)
                if producer is None:
                    print(payload, flush=True)
                else:
                    failures = []
                    def delivered(error, message):
                        if error:
                            failures.append(str(error))
                    producer.produce('person.seen', key=event['event_id'], value=payload, on_delivery=delivered)
                    if producer.flush(6) or failures:
                        raise RuntimeError('Broker delivery failed; observation delivery is unhealthy')
                previous_decision = result[0]
                previous_segment = track
                last_publish = observed_time
        if args.command == 'enroll':
            raise ValueError(f'Enrollment incomplete: {len(samples)}/20 usable observations; nothing saved')
    finally:
        if producer is not None and producer.flush(6):
            raise RuntimeError('Broker shutdown flush failed')
