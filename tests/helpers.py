"""여러 테스트가 같이 쓰는 도우미."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_settings(tmp_path: Path, criteria: dict[str, str] | None = None,
                   overrides: str | None = None) -> Path:
    """배포용 settings.toml을 tmp_path에 복사하고 해당 줄만 바꿔요.

    criteria: {키: TOML 값 글자}. 이미 있는 키는 줄을 바꾸고, 없는 키는 [criteria] 끝에 넣어요.
    overrides: [industry.overrides] 본문 전체를 이 글자로 바꿔요.
    """
    text = (ROOT / "settings.toml").read_text(encoding="utf-8")
    for key, value in (criteria or {}).items():
        pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.M)
        if pattern.search(text):
            text = pattern.sub(lambda _: f"{key} = {value}", text, count=1)
        else:
            text = text.replace("\n[report]", f"{key} = {value}\n\n[report]", 1)
    if overrides is not None:
        text = re.sub(r"(\[industry\.overrides\]\n).*?(?=^\[)",
                      lambda m: m.group(1) + overrides + "\n\n", text, count=1, flags=re.S | re.M)
    out = tmp_path / "settings.toml"
    out.write_text(text, encoding="utf-8")
    return out
