"""Local-only llama.cpp embedding adapter tests."""
import json,unittest
from unittest import mock
from memory.local_embedding_provider import LocalEmbeddingProvider,LocalEmbeddingError,_NoRedirectHandler

class Response:
    status=200
    def __init__(self,body): self.body=body
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self): return json.dumps(self.body).encode()

class LocalEmbeddingProviderTests(unittest.TestCase):
    def test_non_loopback_rejected(self):
        with self.assertRaisesRegex(ValueError,"LOOPBACK_URL_REQUIRED"): LocalEmbeddingProvider("https://example.com")
        with self.assertRaisesRegex(ValueError,"LOOPBACK_URL_REQUIRED"): LocalEmbeddingProvider("http://127.0.0.1:8090/redirect?x=1")
    def test_redirects_are_disabled(self):
        handler=_NoRedirectHandler()
        self.assertIsNone(handler.redirect_request(None,None,302,"Found",{},"https://example.com"))
    def test_batch_order_and_payload(self):
        vectors=[[0.1]*3,[0.2]*3]; body={"data":[{"index":1,"embedding":vectors[1]},{"index":0,"embedding":vectors[0]}]}
        opener=mock.Mock(); opener.open.return_value=Response(body)
        with mock.patch("memory.local_embedding_provider.urllib.request.build_opener",return_value=opener):
            result=LocalEmbeddingProvider(dimension=3)(["один","два"])
        self.assertEqual(result,vectors); req=opener.open.call_args.args[0]
        self.assertEqual(req.full_url,"http://127.0.0.1:8090/v1/embeddings")
        self.assertEqual(json.loads(req.data.decode())["input"],["query: один","query: два"])
    def test_unavailable_local_service_has_no_fallback(self):
        opener=mock.Mock(); opener.open.side_effect=OSError("offline")
        with mock.patch("memory.local_embedding_provider.urllib.request.build_opener",return_value=opener):
            with self.assertRaises(LocalEmbeddingError): LocalEmbeddingProvider(dimension=2)(["test"])
    def test_bad_vector_dimension_rejected(self):
        body={"data":[{"index":0,"embedding":[1.0,2.0,3.0]}]}; opener=mock.Mock(); opener.open.return_value=Response(body)
        with mock.patch("memory.local_embedding_provider.urllib.request.build_opener",return_value=opener):
            with self.assertRaisesRegex(LocalEmbeddingError,"DIMENSION_MISMATCH"): LocalEmbeddingProvider(dimension=2)(["test"])
if __name__=="__main__": unittest.main(verbosity=2)
