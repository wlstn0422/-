from casenote.dart import DartClient, with_ext


class _Resp:
    status_code = 200

    def __init__(self, data):
        self._data = data
        self.text = ""

    def json(self):
        return self._data


class _Session:
    def __init__(self):
        self.urls = []

    def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        return _Resp({"status": "000", "message": "정상", "list": [{"rcept_no": "1"}]})


def test_endpoints_get_json_extension():
    assert with_ext("piicDecsn") == "piicDecsn.json"
    assert with_ext("company.json") == "company.json"
    assert with_ext("corpCode.xml") == "corpCode.xml"


def test_detail_and_registration_calls_use_json_urls():
    client = DartClient("x" * 40, cache_dir=None, interval=0)
    client.session = _Session()
    assert client.event_detail("piicDecsn", "00126380", "20261120", "20261120") == [{"rcept_no": "1"}]
    client.registration("estkRs", "00126380", "20261120", "20261120")
    assert client.session.urls == ["https://opendart.fss.or.kr/api/piicDecsn.json",
                                   "https://opendart.fss.or.kr/api/estkRs.json"]
