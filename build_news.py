# -*- coding: utf-8 -*-
"""daily-news2 자동 생성기 (GitHub Actions, API 키 불필요).

index.html의 날짜와 SECTORS 배열만 교체한다. 디자인/스크립트는 건드리지 않는다.

설계 원칙 (2026-08-21 개정):
  1. 한 소스가 막혀도 멈추지 않는다 — 구글 뉴스 RSS -> (완화 질의) -> Bing 뉴스 RSS
     -> 언론사 직접 RSS 순으로 내려가며 시도하고, 각 요청은 재시도+백오프를 한다.
  2. 좋은 데이터를 나쁜 데이터로 덮어쓰지 않는다 — 어떤 분야를 끝내 못 받아오면
     "불러오지 못했습니다" 문구로 덮는 대신 index.html에 이미 있던 그 분야 기사를
     그대로 유지한다(어제 뉴스가 빈 화면보다 낫다).
  3. 재시도가 실제로 재시도가 되게 한다 — 중복 방지 판단을 날짜만으로 하지 않고,
     HTML에 남긴 빌드 마커(오늘 날짜 + 성공 분야 수)로 한다. 아침에 실패한 분야는
     같은 날 재실행에서 다시 시도된다.
  4. 전부 실패하면 커밋하지 않고 exit 1 로 죽는다 -> Actions가 빨간불로 남고,
     다음 재시도 크론이 다시 집는다.

종료 코드: 0 = 갱신함 / 2 = 갱신할 것 없음 / 1 = 전면 실패
"""
import re, sys, html, json, time, random, urllib.request, urllib.parse, urllib.error
import datetime, xml.etree.ElementTree as ET

KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(KST)
WD = ['월', '화', '수', '목', '금', '토', '일'][NOW.weekday()]
DATE_STR = f"{NOW.year}년 {NOW.month}월 {NOW.day}일 ({WD})"
TODAY = NOW.strftime("%Y-%m-%d")

PER_SECTOR = 2          # 분야당 노출 기사 수
MARKER_RE = re.compile(r'<!--\s*news-build:\s*(\{.*?\})\s*-->')

# key, 표시명, 부제, 색, 검색어, 언론사 직접 RSS(최후의 보루)
SECTORS_DEF = [
    ("youth", "청소년", "Youth", "#f59e0b", "청소년", [
        "https://www.hani.co.kr/rss/society/",
        "https://rss.donga.com/national.xml",
    ]),
    ("ai", "AI", "인공지능", "#8b5cf6", "인공지능", [
        "https://zdnet.co.kr/news/news_xml.asp?stype=AI",
        "https://rss.etnews.com/Section902.xml",
    ]),
    ("science", "과학", "Science", "#0ea5e9", "과학 연구", [
        "https://www.hani.co.kr/rss/science/",
        "https://rss.donga.com/science.xml",
    ]),
    ("economy", "경제", "Economy", "#10b981", "경제", [
        "https://www.hani.co.kr/rss/economy/",
        "https://rss.donga.com/economy.xml",
    ]),
    ("world", "국제", "World", "#ef4444", "국제", [
        "https://www.hani.co.kr/rss/international/",
        "https://rss.donga.com/international.xml",
    ]),
    ("education", "교육", "Education", "#ec4899", "교육 학교", [
        "https://www.hani.co.kr/rss/edu/",
        "https://rss.donga.com/national.xml",
    ]),
]

UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
]


def log(msg):
    print(msg, flush=True)


def fetch(url, timeout=20, tries=3):
    """재시도 + 백오프 + UA 회전. 403/429/503은 좀 더 쉬었다 다시 친다."""
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": random.choice(UAS),
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            wait = (4 if e.code in (403, 429, 503) else 2) * (attempt + 1)
        except Exception as e:
            last = type(e).__name__
            wait = 2 * (attempt + 1)
        if attempt < tries - 1:
            time.sleep(wait + random.random())
    raise RuntimeError(last or "unknown")


def parse_rss(data, limit=8):
    """RSS/Atom 공통 파서. [{title, link, source, date}] 반환."""
    root = ET.fromstring(data)
    out = []
    nodes = list(root.iter("item")) or [e for e in root.iter() if e.tag.endswith("}entry")]
    for it in nodes:
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not link:  # Atom
            for l in it:
                if l.tag.endswith("}link") and l.get("href"):
                    link = l.get("href").strip()
                    break
        src_el = it.find("source")
        source = (src_el.text.strip() if src_el is not None and src_el.text else "")
        pub = (it.findtext("pubDate") or "").strip()
        if not pub:
            for c in it:
                if c.tag.endswith("}updated") or c.tag.endswith("}published"):
                    pub = (c.text or "").strip()
                    break
        # 구글 뉴스 제목 끝의 " - 매체명" 분리
        if source and title.endswith(" - " + source):
            title = title[: -(len(source) + 3)].strip()
        elif " - " in title and not source:
            base, _, tail = title.rpartition(" - ")
            if base and 1 <= len(tail) <= 20:
                source, title = tail.strip(), base.strip()
        date_kr = f"{NOW.month}월 {NOW.day}일"
        try:
            dt = datetime.datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S") \
                .replace(tzinfo=datetime.timezone.utc).astimezone(KST)
            date_kr = f"{dt.month}월 {dt.day}일"
        except Exception:
            pass
        title = re.sub(r"<[^>]+>", "", html.unescape(title)).strip()
        source = html.unescape(source).strip() or "뉴스"
        if title and link.startswith("http"):
            out.append({"title": title, "link": link, "source": source, "date": date_kr})
        if len(out) >= limit:
            break
    return out


# ---------- 소스별 수집기 (앞에서부터 순서대로 시도) ----------

def src_google(query, fresh="2d"):
    q = urllib.parse.quote(f"{query} when:{fresh}")
    return parse_rss(fetch(f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"))


def src_bing(query):
    q = urllib.parse.quote(query)
    return parse_rss(fetch(f"https://www.bing.com/news/search?q={q}&format=RSS&setmkt=ko-KR&setlang=ko"))


def src_direct(feeds):
    items = []
    for url in feeds:
        try:
            items += parse_rss(fetch(url, tries=2))
        except Exception as e:
            log(f"      직접 RSS 실패 {url} ({e})")
        if len(items) >= PER_SECTOR:
            break
    return items


def collect(name, query, feeds, seen):
    """한 분야의 기사를 확보할 때까지 소스를 갈아타며 시도한다."""
    attempts = [
        ("구글뉴스(2일)", lambda: src_google(query, "2d")),
        ("구글뉴스(7일)", lambda: src_google(query, "7d")),
        ("Bing뉴스", lambda: src_bing(query)),
        ("언론사RSS", lambda: src_direct(feeds)),
    ]
    for label, fn in attempts:
        try:
            items = fn()
        except Exception as e:
            log(f"   [{name}] {label} 실패: {e}")
            continue
        # 분야끼리 같은 기사가 겹치지 않게 하되, 그 때문에 칸이 비면 채워 넣는다.
        picked, spare = [], []
        for it in items:
            k = re.sub(r"\W+", "", it["title"])
            if k and k in seen:
                spare.append(it)
                continue
            seen.add(k)
            picked.append(it)
            if len(picked) >= PER_SECTOR:
                break
        while len(picked) < PER_SECTOR and spare:
            picked.append(spare.pop(0))
        if picked:
            log(f"   [{name}] {label} 성공 - {len(picked)}건")
            return picked
        log(f"   [{name}] {label}: 새 기사 없음")
    return []


# ---------- index.html 읽기/쓰기 ----------

ITEM_RE = re.compile(
    r'\{\s*h:"(?P<h>[^"]*)",\s*b:"(?P<b>[^"]*)",\s*'
    r'src:"(?P<src>[^"]*)",\s*srcName:"(?P<sn>[^"]*)",\s*yt:"(?P<yt>[^"]*)"\s*\}', re.S)
SECTOR_RE = re.compile(r'\{\s*key:"(?P<key>\w+)",.*?items:\s*\[(?P<items>.*?)\]\s*\}', re.S)


def read_existing(html_txt):
    """현재 HTML의 분야별 기사 블록을 보존용으로 읽어 둔다."""
    got = {}
    block = re.search(r"const SECTORS = \[.*?\n\];", html_txt, re.S)
    if not block:
        return got
    for m in SECTOR_RE.finditer(block.group(0)):
        items = [dict(h=i.group("h"), b=i.group("b"), src=i.group("src"),
                      srcName=i.group("sn"), yt=i.group("yt"))
                 for i in ITEM_RE.finditer(m.group("items"))]
        items = [i for i in items if "불러오지 못했습니다" not in i["h"]]
        if items:
            got[m.group("key")] = items
    return got


def jsstr(s):
    return s.replace("\\", "").replace('"', "'").replace("\n", " ").replace("\r", " ").strip()


def yt_link(q):
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote(q)


def to_entry(it):
    return {
        "h": jsstr(it["title"]),
        "b": jsstr(f'{it["source"]} · {it["date"]} 보도. 자세한 내용은 출처 링크에서 확인하세요.'),
        "src": jsstr(it["link"]),
        "srcName": jsstr(it["source"]),
        "yt": jsstr(yt_link(it["title"])),
    }


def render(sectors):
    out = ["const SECTORS = ["]
    for i, (key, name, en, color, entries) in enumerate(sectors):
        out.append(f'  {{ key:"{key}", name:"{name}", en:"{en}", color:"{color}",')
        out.append("    items:[")
        for j, e in enumerate(entries):
            tail = "" if j == len(entries) - 1 else ","
            out.append(f'      {{ h:"{e["h"]}", b:"{e["b"]}",')
            out.append(f'        src:"{e["src"]}", srcName:"{e["srcName"]}", yt:"{e["yt"]}" }}{tail}')
        out.append("    ]}" + ("" if i == len(sectors) - 1 else ","))
    out.append("];")
    return "\n".join(out)


def main():
    html_txt = open("index.html", encoding="utf-8").read()
    existing = read_existing(html_txt)

    # --- 중복 방지: 날짜만이 아니라 "오늘 + 전 분야 성공"일 때만 건너뛴다 ---
    mk = MARKER_RE.search(html_txt)
    if mk:
        try:
            info = json.loads(mk.group(1))
            if info.get("date") == TODAY and info.get("ok") == len(SECTORS_DEF):
                log(f"오늘({TODAY}) 전 분야 갱신 완료 -> 변경 없음")
                return 2
        except Exception:
            pass
    else:
        m = re.search(r'id="date"[^>]*>([^<]*)<', html_txt)
        if m and m.group(1).strip() == DATE_STR and "불러오지 못했습니다" not in html_txt:
            log("이미 오늘 날짜이고 실패 문구도 없음 -> 변경 없음")
            return 2

    seen, sectors, ok, stale = set(), [], 0, []
    for key, name, en, color, query, feeds in SECTORS_DEF:
        items = collect(name, query, feeds, seen)
        if items:
            ok += 1
            sectors.append((key, name, en, color, [to_entry(i) for i in items]))
        elif key in existing:
            stale.append(name)
            log(f"   [{name}] 전 소스 실패 -> 기존 기사 유지")
            sectors.append((key, name, en, color, existing[key]))
        else:
            stale.append(name)
            log(f"   [{name}] 전 소스 실패, 보존할 기존 기사도 없음")
            sectors.append((key, name, en, color, [{
                "h": jsstr(f"{name} 뉴스를 불러오지 못했습니다"),
                "b": jsstr("잠시 후 자동으로 다시 시도합니다. 아래 출처 링크에서 바로 확인할 수 있습니다."),
                "src": f"https://news.google.com/search?q={urllib.parse.quote(query)}&hl=ko",
                "srcName": "Google 뉴스",
                "yt": jsstr(yt_link(query + " 뉴스")),
            }]))

    if ok == 0:
        log("모든 분야 수집 실패 -> 커밋하지 않고 종료(다음 재시도에 맡김)")
        return 1

    new_sectors = render(sectors)
    out = re.sub(r'(<div class="date" id="date">)[^<]*(</div>)',
                 lambda m: m.group(1) + DATE_STR + m.group(2), html_txt, count=1)
    out = re.sub(r"const SECTORS = \[.*?\n\];", lambda _: new_sectors, out, count=1, flags=re.S)

    marker = '<!-- news-build: ' + json.dumps(
        {"date": TODAY, "at": NOW.strftime("%H:%M"), "ok": ok, "stale": stale},
        ensure_ascii=False) + ' -->'
    if MARKER_RE.search(out):
        out = MARKER_RE.sub(lambda _: marker, out, count=1)
    else:
        out = out.replace("</body>", marker + "\n</body>", 1)

    open("index.html", "w", encoding="utf-8").write(out)
    log(f"갱신 완료: {DATE_STR} - 성공 {ok}/{len(SECTORS_DEF)} 분야" +
        (f", 기존 유지: {', '.join(stale)}" if stale else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
