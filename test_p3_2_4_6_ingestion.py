"""P3.2.4.6: protect ingestion from lexical-overlap data loss."""
import json, os, shutil, tempfile, unittest
from unittest import mock
from memory import memory_core

def record(identifier,text):
    return {"id":identifier,"timestamp":"2026-01-01 10:00:00","text":text,"category":"facts","importance":5,"source":"user","topics":[]}

class IngestionPreservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.mkdtemp(prefix="p3_2_4_6_"); self.path=os.path.join(self.tmp,"memory.json")
        self.patch=mock.patch.object(memory_core,"MEMORY_FILE",self.path); self.patch.start()
        self.addCleanup(self.patch.stop); self.addCleanup(lambda:shutil.rmtree(self.tmp,ignore_errors=True))
    def write(self,entries):
        with open(self.path,"w",encoding="utf-8") as f: json.dump({"version":2,"entries":entries},f,ensure_ascii=False)
    def test_changed_numeric_fact_is_saved_without_rewriting_old_record(self):
        original=record("old","Роман использует 8 GB памяти на Poco F6"); self.write([original])
        with mock.patch.object(memory_core,"_save_raw") as save:
            result=memory_core.add_memory("Роман использует 12 GB памяти на Poco F6 во время поездок",category="facts",source="user")
        self.assertTrue(result.startswith("Сохранено"),result)
        entries=save.call_args.args[0]["entries"]
        self.assertEqual(len(entries),2); self.assertEqual(entries[0]["text"],original["text"])
        self.assertEqual(entries[0]["source"],original["source"])
    def test_longer_lexical_overlap_does_not_refine_existing_fact(self):
        original=record("old","Brain использует локальную модель"); self.write([original])
        with mock.patch.object(memory_core,"_save_raw") as save:
            result=memory_core.add_memory("Brain использует локальную модель и отдельный embedding-сервер",source="user")
        self.assertTrue(result.startswith("Сохранено"),result)
        self.assertEqual(save.call_args.args[0]["entries"][0]["text"],original["text"])
        self.assertEqual(len(save.call_args.args[0]["entries"]),2)
    def test_exact_normalized_duplicate_is_still_suppressed(self):
        self.write([record("old","Роман живёт в Германии")])
        with mock.patch.object(memory_core,"_save_raw") as save:
            result=memory_core.add_memory("  Роман живёт в Германии  ",source="user")
        self.assertIn("Уже есть",result); save.assert_not_called()
    def test_contradiction_superseding_is_preserved(self):
        original=record("old","Старое подтверждённое состояние"); self.write([original])
        with mock.patch.object(memory_core,"_find_contradictions",return_value=[original]), mock.patch.object(memory_core,"_save_raw") as save:
            result=memory_core.add_memory("Новое подтверждённое состояние",source="user")
        self.assertTrue(result.startswith("Сохранено"),result)
        self.assertEqual(save.call_args.args[0]["entries"][0]["status"],"superseded")

if __name__=="__main__": unittest.main(verbosity=2)
