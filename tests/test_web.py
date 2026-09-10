from app.agent.web import crossref_summary


def test_crossref_summary_is_readable_and_not_raw_json():
    item = {
        'title':['A Model of Two Tales'],
        'container-title':['Proceedings of The Web Conference 2021'],
        'type':'proceedings-article',
        'published':{'date-parts':[[2021,4,19]]},
        'publisher':'ACM',
        'DOI':'10.1145/example',
        'event':{'name':'WWW 21','location':'Ljubljana, Slovenia'},
    }
    summary = crossref_summary(item)
    assert '出版载体：Proceedings of The Web Conference 2021' in summary
    assert '文献类型：会议论文' in summary
    assert '发表日期：2021-04-19' in summary
    assert '会议地点：Ljubljana, Slovenia' in summary
    assert not summary.lstrip().startswith('{')
