"""End-to-end local-provider and guarded-preview tests using temporary memory."""
import json,os,shutil,tempfile,unittest
from unittest import mock
from memory import memory_core
from memory.fact_frame_extractor import extract_fact_frames
from memory.local_embedding_provider import LocalEmbeddingProvider

class GuardedProviderIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.mkdtemp(prefix="p3_2_4_9_"); self.path=os.path.join(self.tmp,"memory.json")
        self.patch=mock.patch.object(memory_core,"MEMORY_FILE",self.path); self.patch.start()
        self.addCleanup(self.patch.stop); self.addCleanup(lambda:shutil.rmtree(self.tmp,ignore_errors=True))
    def write(self,entries):
        with open(self.path,"w",encoding="utf-8") as f: json.dump({"version":2,"entries":entries},f,ensure_ascii=False)
    def test_local_provider_extractor_and_guard_are_read_only(self):
        self.write([{"id":"a","text":"Роман проживает в Германии","category":"facts","source":"user","status":"active"},
                    {"id":"b","text":"Роман живёт в Германии","category":"facts","source":"user","status":"active"}])
        vectors=[[1.0,0.0]+[0.0]*382,[0.999,0.01]+[0.0]*382]
        body={"data":[{"index":i,"embedding":v} for i,v in enumerate(vectors)]}
        class Resp:
            status=200
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self): return json.dumps(body).encode()
        with mock.patch("memory.local_embedding_provider.urllib.request.urlopen",return_value=Resp()) as post:
            before=open(self.path,"rb").read()
            result=memory_core.preview_guarded_semantic_memory_consolidation(LocalEmbeddingProvider(),extract_fact_frames)
            after=open(self.path,"rb").read()
        self.assertEqual(len(result),1); self.assertEqual(result[0]["candidate_policy"],"guarded_semantic_review_only")
        self.assertEqual(before,after); post.assert_called_once()
    def test_unsupported_related_sentences_fail_closed(self):
        self.write([{"id":"a","text":"Перегрев смартфона увеличивает скорость разряда батареи","category":"facts","source":"user"},
                    {"id":"b","text":"Повышенная температура ускоряет износ аккумулятора","category":"facts","source":"user"}])
        result=memory_core.preview_guarded_semantic_memory_consolidation(lambda texts:[[1.0,0.0] for _ in texts],extract_fact_frames)
        self.assertEqual(result,[])
if __name__=="__main__": unittest.main(verbosity=2)
