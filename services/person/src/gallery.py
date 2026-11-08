"""Private local gallery. Atomic writes under an exclusive file lock."""
import fcntl
import hashlib
import json
from pathlib import Path
import re
import uuid
import numpy as np
from .recognition import unit
from .storage import atomic_json


class Gallery:
    def __init__(self, path, model):
        self.path, self.model = Path(path), model
        self.people = {}
        self.revision = None
        self.provenance = {}
        if self.path.exists():
            data = json.loads(self.path.read_text())
            if data['version'] != 1 or data['model'] != model:
                raise ValueError('Gallery model/preprocessing mismatch; re-enroll')
            self.revision = data.get('revision')
            self.provenance = data.get('provenance', {})
            self.people = data['people']
            dimensions = set()
            for templates in self.people.values():
                if not templates:
                    raise ValueError('Gallery identity has no templates')
                for vector in templates:
                    unit(vector)  # Validate without changing persisted values or their fingerprint.
                    if not np.isclose(np.linalg.norm(vector), 1.):
                        raise ValueError('Gallery template must be normalized')
                    dimensions.add(len(vector))
            if len(dimensions) > 1:
                raise ValueError('Gallery template dimensions disagree')

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps([self.revision, self.people], sort_keys=True).encode()).hexdigest()

    def _save_change(self, person, templates, provenance=None):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            current = Gallery(self.path, self.model)
            if templates is None:
                if person not in current.people:
                    raise ValueError('Person is not enrolled')
                del current.people[person]
                current.provenance.pop(person, None)
            else:
                if person in current.people:
                    raise ValueError('Person already enrolled; remove explicitly first')
                current.people[person] = templates
                current.provenance[person] = provenance or {}
            current.revision = str(uuid.uuid4())
            atomic_json(self.path, {'version': 1, 'model': self.model, 'people': current.people,
                                    'revision': current.revision, 'provenance': current.provenance})
            self.revision = current.revision
            self.provenance = current.provenance
            self.people = current.people

    def enroll(self, person, samples, provenance=None):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', person):
            raise ValueError('Person ID must contain 1–64 letters, digits, underscores or hyphens')
        if len(samples) < 10:
            raise ValueError('Enrollment needs at least 10 usable observations')
        # shortcut: one averaged template; add pose bins after held-out baseline evaluation.
        template = unit(sum(unit(v) for v in samples)).tolist()
        self._save_change(person, [template], provenance)

    def remove(self, person):
        self._save_change(person, None)

    def scores(self, vector):
        vector = unit(vector)
        return {person: float(max(np.dot(vector, template) for template in templates))
                for person, templates in self.people.items()}


class DualGallery:
    """Manages strictly separate ArcFace and AdaFace galleries with identical identities."""
    def __init__(self, arcface_gallery, adaface_gallery):
        self.arcface = arcface_gallery
        self.adaface = adaface_gallery
        if set(self.arcface.people.keys()) != set(self.adaface.people.keys()):
            raise ValueError('DualGallery identities mismatch; ArcFace and AdaFace must cover the same people')

    @property
    def people(self):
        return set(self.arcface.people.keys())

    @property
    def fingerprint(self):
        return hashlib.sha256(f'{self.arcface.fingerprint}:{self.adaface.fingerprint}'.encode()).hexdigest()

    def enroll(self, person, arc_samples, ada_samples, provenance=None):
        self.arcface.enroll(person, arc_samples, provenance=provenance)
        try:
            self.adaface.enroll(person, ada_samples, provenance=provenance)
        except Exception:
            try:
                self.arcface.remove(person)
            except Exception:
                pass
            raise

    def remove(self, person):
        self.arcface.remove(person)
        self.adaface.remove(person)

    def scores(self, arc_vector, ada_vector):
        return self.arcface.scores(arc_vector), self.adaface.scores(ada_vector)

