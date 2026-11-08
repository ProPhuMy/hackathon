import json
from types import SimpleNamespace
from conftest import score_dataset
from src.cli.scores import execute


def test_json_artifacts_roundtrip_through_cli_handler(tmp_path, capsys):
    paths = {}
    for split in ('dev', 'conformal', 'test'):
        path = tmp_path / f'{split}.json'
        path.write_text(json.dumps(score_dataset(split)))
        paths[split] = path
    policy = tmp_path / 'policy.json'
    execute(SimpleNamespace(command='calibrate-scores', development=paths['dev'], conformal=paths['conformal'], output=policy))
    output = tmp_path / 'report.json'
    execute(SimpleNamespace(command='evaluate-scores', scores=paths['test'], policy=policy, output=output))
    assert json.loads(output.read_text())['known_correct'] == 24
