#!/usr/bin/env python3
"""
유튜브 영상 분야별 모음 — youtube.html 생성기

상태 파일: youtube_videos.json  (분야별 영상 목록 + 목록에 들어온 날짜)
원본:      노션 '유튜브 영상 분야별 모음' 페이지 (## 분야 제목 + 글머리표 링크)

사용법
  python build_youtube.py merge notion.md   # 노션 페이지 마크다운을 JSON에 반영 (신규=오늘 날짜, 삭제 반영)
  python build_youtube.py render            # JSON → youtube.html 의 자동 갱신 영역만 교체
  python build_youtube.py check             # JSON과 youtube.html 스크립트 문법 점검

merge 입력(notion.md)은 Notion MCP fetch 결과 <content> 중 '## ' 분야 제목부터
마지막 분야의 목록까지를 그대로 저장한 파일이다. 아래 두 형식을 모두 읽는다.
  - [제목](https://app.notion.com/p/<id>) (13:44)
  - \\[제목\\](<mention-page url="https://app.notion.com/p/<id>"/>) (48:02)
노션 페이지가 아닌 외부 링크(유튜브 URL 등)는 u 필드로 보관한다.
"""
import json, re, sys, os, datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(HERE, "youtube_videos.json")
HTML_PATH = os.path.join(HERE, "youtube.html")
START = "/* ===== 영상 데이터 (자동 갱신 영역 시작) ===== */"
END = "/* ===== 영상 데이터 (자동 갱신 영역 끝) ===== */"

# 분야 순서·색은 여기서만 관리한다. 노션 제목의 이모지는 무시하고 이름으로 매칭한다.
CATS = [
    {"k": "AI",        "color": "#C25E4A"},
    {"k": "로봇",      "color": "#B08D57"},
    {"k": "과학",      "color": "#3E7C59"},
    {"k": "강의",      "color": "#3F6FA8"},
    {"k": "공부법",    "color": "#5B8C5A"},
    {"k": "뇌과학",    "color": "#C79A2E"},
    {"k": "시사·뉴스", "color": "#B34A3F"},
    {"k": "자동화",    "color": "#6E6A63"},
]
CAT_KEYS = [c["k"] for c in CATS]

KST = ZoneInfo("Asia/Seoul")


def now_kst():
    return datetime.datetime.now(KST)


def load_json():
    if not os.path.exists(JSON_PATH):
        return {"synced_at": "", "videos": []}
    with open(JSON_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_json(data):
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def unescape_md(s):
    return re.sub(r"\\([\[\]|*_`#()])", r"\1", s).strip()


LINE_RE = re.compile(
    r"^\s*[-*]\s+\\?\[(?P<title>.*?)\\?\]\("
    r"(?:<mention-page url=\"(?P<murl>[^\"]+)\"/>|(?P<url>[^)\s]+))\)"
    r"\s*(?:\((?P<meta>[^)]*)\))?\s*$"
)
DUR_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")


def parse_notion_md(text):
    """→ [{t, i|u, c, d, note}] 노션 순서대로"""
    out, cat = [], None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            name = re.sub(r"[^\w가-힣·]+", "", line[3:])
            cat = next((k for k in CAT_KEYS if k.replace("·", "") == name.replace("·", "")), None)
            if cat is None:
                # 노션에 새 분야가 생기면 그대로 받아들인다 (색은 render 때 회색)
                cat = line[3:].strip()
                cat = re.sub(r"^[^\w가-힣]+", "", cat).strip()
            continue
        m = LINE_RE.match(line)
        if not m or cat is None:
            continue
        title = unescape_md(m.group("title"))
        url = m.group("murl") or m.group("url")
        meta = (m.group("meta") or "").strip()
        dur, note = "", ""
        if meta:
            parts = [p.strip() for p in meta.split(",")]
            if DUR_RE.match(parts[0]):
                dur, note = parts[0], ", ".join(parts[1:])
            else:
                note = meta
        item = {"t": title, "c": cat, "d": dur}
        pid = re.search(r"notion\.(?:so|com)/(?:p/)?(?:[^/?#]*-)?([0-9a-f]{32})", url)
        if pid:
            item["i"] = pid.group(1)
        else:
            item["u"] = url
        if note:
            item["n"] = note
        out.append(item)
    return out


def key_of(v):
    return v.get("i") or v.get("u")


def cmd_merge(md_path):
    text = open(md_path, encoding="utf-8").read()
    fresh = parse_notion_md(text)
    if len(fresh) < 10:
        sys.exit(f"[merge] 노션 목록이 {len(fresh)}편뿐입니다. 입력 파일이 잘못된 것 같아 중단합니다.")
    data = load_json()
    old = {key_of(v): v for v in data["videos"]}
    today = now_kst().strftime("%Y-%m-%d")
    seen, merged, added, changed = set(), [], [], []
    for v in fresh:
        k = key_of(v)
        if k in seen:          # 노션에 같은 영상이 두 번 있으면 첫 것만
            continue
        seen.add(k)
        prev = old.get(k)
        if prev:
            nv = dict(prev)
            for f in ("t", "c", "d", "n", "u"):
                if v.get(f) != prev.get(f):
                    changed.append((v["t"], f))
                if f in v:
                    nv[f] = v[f]
                elif f in nv and f != "a":
                    del nv[f]
            merged.append(nv)
        else:
            v["a"] = today
            merged.append(v)
            added.append(v["t"])
    removed = [old[k]["t"] for k in old if k not in seen]
    data["videos"] = merged
    data["synced_at"] = now_kst().strftime("%Y-%m-%d %H:%M")
    save_json(data)
    print(f"[merge] 총 {len(merged)}편 · 신규 {len(added)} · 제거 {len(removed)} · 수정 {len(changed)}")
    for t in added:
        print("  + " + t)
    for t in removed:
        print("  - " + t)
    for t, f in changed:
        print(f"  ~ ({f}) " + t)


def js_str(s):
    return json.dumps(s, ensure_ascii=False)


def cmd_render():
    data = load_json()
    videos = data["videos"]
    cats = list(CATS)
    for v in videos:  # 노션에 새 분야가 있으면 뒤에 추가
        if v["c"] not in [c["k"] for c in cats]:
            cats.append({"k": v["c"], "color": "#8A8175"})

    lines = [START,
             f'const SYNCED_AT = {js_str(data["synced_at"])};',
             "const CATS = ["]
    lines += [f'  {{k:{js_str(c["k"])}, label:{js_str(c["k"])}, color:{js_str(c["color"])}}},' for c in cats]
    lines[-1] = lines[-1].rstrip(",")
    lines.append("];")
    lines.append("// t=제목, i=노션 페이지 id(또는 u=외부 링크), c=분야, d=길이(모르면 \"\"), n=비고, a=목록에 들어온 날짜")
    lines.append("const VIDEOS = [")
    body = []
    for c in cats:
        items = [v for v in videos if v["c"] == c["k"]]
        if not items:
            continue
        for v in items:
            fields = [f"t:{js_str(v['t'])}"]
            fields.append(f"i:{js_str(v['i'])}" if v.get("i") else f"u:{js_str(v['u'])}")
            fields += [f"c:{js_str(v['c'])}", f"d:{js_str(v.get('d', ''))}"]
            if v.get("n"):
                fields.append(f"n:{js_str(v['n'])}")
            fields.append(f"a:{js_str(v.get('a', ''))}")
            body.append("  {" + ", ".join(fields) + "},")
        body.append("")
    while body and body[-1] == "":
        body.pop()
    if body:
        body[-1] = body[-1].rstrip(",")
    lines += body
    lines += ["];", END]
    block = "\n".join(lines)

    html = open(HTML_PATH, encoding="utf-8").read()
    s, e = html.find(START), html.find(END)
    if s < 0 or e < 0:
        sys.exit("[render] youtube.html 에서 자동 갱신 영역 표식을 찾지 못했습니다.")
    new_html = html[:s] + block + html[e + len(END):]
    if new_html == html:
        print("[render] 변경 없음")
        return 2
    open(HTML_PATH, "w", encoding="utf-8").write(new_html)
    print(f"[render] youtube.html 갱신 — 총 {len(videos)}편, 분야 {len([c for c in cats if any(v['c']==c['k'] for v in videos)])}개")
    return 0


def cmd_check():
    data = load_json()
    keys = [key_of(v) for v in data["videos"]]
    dup = {k for k in keys if keys.count(k) > 1}
    assert not dup, f"중복 id: {dup}"
    for v in data["videos"]:
        assert v.get("t") and v.get("c") and (v.get("i") or v.get("u")), v
        assert v.get("a"), f"a 없음: {v['t']}"
    html = open(HTML_PATH, encoding="utf-8").read()
    s, e = html.find(START), html.find(END)
    assert 0 <= s < e, "표식 없음"
    import subprocess, tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(html[s:e + len(END)])
        f.write("\nif(VIDEOS.length<10) throw new Error('too few'); console.log('OK', VIDEOS.length, 'videos');")
        p = f.name
    r = subprocess.run(["node", p], capture_output=True, text=True)
    os.unlink(p)
    if r.returncode != 0:
        sys.exit("[check] JS 오류:\n" + r.stderr)
    print("[check]", r.stdout.strip())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "merge":
        cmd_merge(sys.argv[2])
    elif cmd == "render":
        sys.exit(cmd_render())
    elif cmd == "check":
        cmd_check()
    else:
        sys.exit(__doc__)
