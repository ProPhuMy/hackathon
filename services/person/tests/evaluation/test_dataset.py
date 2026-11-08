import pytest
from src.evaluation.dataset import read_manifest, verify_disjoint


def test_manifest_resolves_paths_and_checks_split(tmp_path):
    (tmp_path / 'probe.avi').write_bytes(b'video')
    manifest = tmp_path / 'dev.csv'
    manifest.write_text('path,person_id,session_id,split,start_s,end_s\nprobe.avi,p_01,dev-1,development,0,1\n')
    rows = read_manifest(manifest, 'development')
    assert rows[0]['path'] == str(tmp_path / 'probe.avi')
    with pytest.raises(ValueError, match='split'):
        read_manifest(manifest, 'test')
    with pytest.raises(ValueError, match='overlap'):
        verify_disjoint(rows, rows)


def test_duplicate_encounters_and_nonfinite_ranges_are_rejected(tmp_path):
    (tmp_path / 'a.avi').write_bytes(b'a')
    manifest = tmp_path / 'dev.csv'
    header = 'path,person_id,session_id,split,start_s,end_s\n'
    row = 'a.avi,p_01,s1,development,0,1\n'
    manifest.write_text(header + row + row)
    with pytest.raises(ValueError):
        read_manifest(manifest, 'development')
    manifest.write_text(header + 'a.avi,p_01,s1,development,nan,1\n')
    with pytest.raises(ValueError):
        read_manifest(manifest, 'development')


def test_same_recording_cannot_be_counted_as_two_encounters(tmp_path):
    (tmp_path / 'a.avi').write_bytes(b'one-recording')
    (tmp_path / 'copy.avi').write_bytes(b'one-recording')
    manifest = tmp_path / 'dev.csv'
    manifest.write_text('path,person_id,session_id,split,start_s,end_s\n'
                        'a.avi,a,s1,development,0,1\n'
                        'copy.avi,a,s2,development,0,1\n')
    with pytest.raises(ValueError, match='recording'):
        read_manifest(manifest, 'development')


def test_manifest_clips_get_the_same_rotation_as_live_capture(tmp_path):
    from conftest import is_turned_clockwise, left_lit_clip
    from src.evaluation.dataset import observations
    seen = []
    class Vision:
        def single_face(self, image):
            seen.append(image)
            return None
    row = {'path': str(left_lit_clip(tmp_path / 'clip.avi')), 'person_id': None, 'start_s': 0., 'end_s': 10.}
    observations(row, Vision(), rotation=90)
    assert seen and all(is_turned_clockwise(image) for image in seen)
