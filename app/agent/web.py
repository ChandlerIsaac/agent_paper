"""Bounded public search tool. Results are evidence candidates, not verified facts."""
import time
from urllib.parse import urlparse
import httpx
from langchain_core.tools import tool


def first_text(value):
    if isinstance(value,list):
        return str(value[0]) if value else ''
    return str(value or '')


def crossref_summary(item):
    """Format selected bibliographic fields for people, not as raw JSON."""
    published = item.get('published') or item.get('published-print') or item.get('published-online') or {}
    parts = (published.get('date-parts') or [[]])[0]
    date = '-'.join(str(x).zfill(2) if index else str(x)
                    for index,x in enumerate(parts))
    event = item.get('event') if isinstance(item.get('event'),dict) else {}
    kind = {
        'proceedings-article':'会议论文',
        'journal-article':'期刊论文',
        'book-chapter':'书籍章节',
        'posted-content':'预印本或在线内容',
    }.get(item.get('type'),item.get('type',''))
    fields = [
        ('标题',first_text(item.get('title'))),
        ('出版载体',first_text(item.get('container-title'))),
        ('文献类型',kind),
        ('发表日期',date),
        ('出版方',item.get('publisher','')),
        ('会议名称',event.get('name','')),
        ('会议简称',event.get('acronym','')),
        ('会议地点',event.get('location','')),
        ('DOI',item.get('DOI','')),
    ]
    return '\n'.join(f'{label}：{value}' for label,value in fields if value)


def make_web_search(settings):
    @tool
    def search_web(query: str) -> dict:
        """Search public scholarly metadata or web pages; only send a short search query."""
        query = query.strip()[:500]
        if not query:
            return {'results': [], 'error': '搜索词为空'}
        started = time.monotonic()
        provider = settings.web_search_provider
        try:
            with httpx.Client(timeout=settings.web_search_timeout) as client:
                if settings.web_search_provider == 'tavily':
                    if not settings.tavily_api_key:
                        return {'results': [], 'error': '尚未配置 TAVILY_API_KEY'}
                    response = client.post('https://api.tavily.com/search',
                        headers={'Authorization': 'Bearer '+settings.tavily_api_key.get_secret_value()},
                        json={'query':query,'max_results':5,'search_depth':'basic','include_answer':False})
                    response.raise_for_status()
                    results = [dict(title=x.get('title','网页'),url=x.get('url',''),
                                    content=x.get('content','')[:1800])
                               for x in response.json().get('results',[])[:5]]
                else:
                    response = client.get('https://api.crossref.org/works',
                        params={'query.bibliographic':query,'rows':5},
                        headers={'User-Agent':'ResearchMate/0.2 (scholarly metadata search)'})
                    response.raise_for_status()
                    results = []
                    for item in response.json().get('message',{}).get('items',[])[:5]:
                        results.append(dict(title='; '.join(item.get('title',[])),
                            url='https://doi.org/'+item['DOI'] if item.get('DOI') else item.get('URL',''),
                            content=crossref_summary(item)))
            results = [x for x in results if urlparse(x['url']).scheme in ('https','http')]
            return {'results':results,'provider':provider,
                    'elapsed_seconds':round(time.monotonic()-started,2)}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return {'results':[],'provider':provider,
                    'elapsed_seconds':round(time.monotonic()-started,2),
                    'error':'联网搜索失败或超时，请检查服务器网络与搜索服务配置'}
    search_web.metadata = {'provider':settings.web_search_provider}
    return search_web
