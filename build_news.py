# -*- coding: utf-8 -*-
"""daily-news2 자동 생성기 (GitHub Actions, 키 불필요).
Google 뉴스 RSS(카테고리 검색)에서 6개 섹터 각 2건을 모아 index.html의
날짜와 SECTORS 배열만 교체한다. 디자인/스크립트는 그대로 둔다."""
import re, sys, html, urllib.request, urllib.parse, datetime, xml.etree.ElementTree as ET

KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(KST)
WD = ['월','화','수','목','금','토','일'][NOW.weekday()]
DATE_STR = f"{NOW.year}년 {NOW.month}월 {NOW.day}일 ({WD})"

SECTORS_DEF = [
    ("youth","청소년","Youth","#f59e0b","청소년"),
    ("ai","AI","인공지능","#8b5cf6","인공지능"),
    ("science","과학","Science","#0ea5e9","과학 연구"),
    ("economy","경제","Economy","#10b981","경제"),
    ("world","국제","World","#ef4444","국제"),
    ("education","교육","Education","#ec4899","교육 학교"),
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def gnews(query, n=2):
    q = urllib.parse.quote(query + " when:2d")
    url = f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"
    data = fetch(url)
    root = ET.fromstring(data)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        src_el = it.find("source")
        source = (src_el.text.strip() if src_el is not None and src_el.text else "")
        pub = (it.findtext("pubDate") or "").strip()
        # 제목 끝의 " - 매체명" 제거
        if source and title.endswith(" - " + source):
            title = title[: -(len(source) + 3)].strip()
        elif " - " in title:
            base, _, tail = title.rpartition(" - ")
            if not source:
                source = tail.strip()
            title = base.strip()
        # 날짜 -> M월 D일
        date_kr = ""
        try:
            dt = datetime.datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S").replace(tzinfo=datetime.timezone.utc).astimezone(KST)
            date_kr = f"{dt.month}월 {dt.day}일"
        except Exception:
            date_kr = f"{NOW.month}월 {NOW.day}일"
        title = html.unescape(title)
        source = html.unescape(source) or "뉴스"
        if title and link:
            items.append({"title": title, "source": source, "link": link, "date": date_kr})
        if len(items) >= n:
            break
    return items

def yt(q):
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote(q)

def jsstr(s):
    # JS 큰따옴표 문자열 안전화: 역슬래시/큰따옴표 제거·치환
    return s.replace("\\", "").replace('"', "'").replace("\n", " ").replace("\r", " ").strip()

def build_sectors():
    blocks = ["const SECTORS = ["]
    for key, name, en, color, query in SECTORS_DEF:
        try:
            items = gnews(query, 2)
        except Exception as e:
            items = []
        if not items:
            items = [{"title": f"{name} 관련 최신 뉴스를 불러오지 못했습니다", "source": "Google 뉴스",
                      "link": f"https://news.google.com/search?q={urllib.parse.quote(query)}&hl=ko", "date": f"{NOW.month}월 {NOW.day}일"}]
        blocks.append(f'  {{ key:"{key}", name:"{name}", en:"{en}", color:"{color}",')
        blocks.append('    items:[')
        for i, it in enumerate(items):
            h = jsstr(it["title"])
            b = jsstr(f'{it["source"]} · {it["date"]} 보도. 자세한 내용은 출처 링크에서 확인하세요.')
            src = jsstr(it["link"])
            sn = jsstr(it["source"])
            y = yt(it["title"])
            comma = "" if i == len(items) - 1 else ","
            blocks.append(f'      {{ h:"{h}", b:"{b}",')
            blocks.append(f'        src:"{src}", srcName:"{sn}", yt:"{y}" }}{comma}')
        blocks.append("    ]},")
    for i in range(len(blocks) - 1, -1, -1):
        if blocks[i] == "    ]},":
            blocks[i] = "    ]}"
            break
    blocks.append("];")
    return "\n".join(blocks)

def main():
    html_txt = open("index.html", encoding="utf-8").read()
    # 멱등성: 이미 오늘 날짜면 아무 것도 하지 않음(재실행 시 중복 커밋 방지)
    m = re.search(r'id="date"[^>]*>([^<]*)<', html_txt)
    if m and m.group(1).strip() == DATE_STR:
        print("이미 오늘 날짜:", DATE_STR, "-> 변경 없음")
        return
    new_sectors = build_sectors()
    out = re.sub(r'(<div class="date" id="date">)[^<]*(</div>)', r'\g<1>' + DATE_STR + r'\g<2>', html_txt, count=1)
    out = re.sub(r"const SECTORS = \[.*?\n\];", lambda _: new_sectors, out, count=1, flags=re.S)
    open("index.html", "w", encoding="utf-8").write(out)
    print("갱신 완료:", DATE_STR)

if __name__ == "__main__":
    main()
