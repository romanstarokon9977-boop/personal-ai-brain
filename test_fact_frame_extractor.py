"""Conservative FactFrame extractor tests."""
import unittest
from memory.fact_frame_extractor import extract_fact_frame,extract_fact_frames
from memory.semantic_guardrails import analyze_fact_pair

class FactFrameExtractorTests(unittest.TestCase):
    def rec(self,i,text,source="user"): return {"id":i,"text":text,"source":source,"category":"facts"}
    def test_location_paraphrases_match(self):
        a=self.rec("a","Роман проживает в Германии"); b=self.rec("b","Роман живёт в Германии")
        self.assertEqual(extract_fact_frame(a),extract_fact_frame(b))
        self.assertEqual(analyze_fact_pair(a,b,extract_fact_frame(a),extract_fact_frame(b)).decision,"CANDIDATE_FOR_REVIEW")
    def test_numeric_roles_and_units_are_distinct(self):
        a=self.rec("a","Устройство имеет 8 GB RAM"); b=self.rec("b","Устройство имеет 8 TB storage")
        fa=extract_fact_frame(a); fb=extract_fact_frame(b)
        self.assertNotEqual(fa.semantic_role,fb.semantic_role); self.assertNotEqual(fa.unit,fb.unit)
        self.assertEqual(analyze_fact_pair(a,b,fa,fb).relation,"CONTRADICTION")
    def test_implicit_opposites_are_distinct(self):
        a=self.rec("a","Сервер доступен для подключения"); b=self.rec("b","Сервер недоступен для подключения")
        self.assertEqual(analyze_fact_pair(a,b,extract_fact_frame(a),extract_fact_frame(b)).relation,"CONTRADICTION")
    def test_presence_absence_is_distinct(self):
        a=self.rec("a","Резервное копирование активно"); b=self.rec("b","Резервное копирование отключено")
        self.assertEqual(analyze_fact_pair(a,b,extract_fact_frame(a),extract_fact_frame(b)).relation,"CONTRADICTION")
    def test_different_subjects_are_distinct(self):
        a=self.rec("a","Роман использует 8 GB RAM"); b=self.rec("b","Мария использует 8 GB RAM")
        self.assertEqual(analyze_fact_pair(a,b,extract_fact_frame(a),extract_fact_frame(b)).reason_codes,("SUBJECT_MISMATCH",))
    def test_multiple_numeric_roles_fail_closed(self):
        self.assertIsNone(extract_fact_frame(self.rec("x","Устройство имеет 8 GB RAM и 256 GB storage")))
    def test_unsupported_causal_fact_fails_closed(self):
        self.assertIsNone(extract_fact_frame(self.rec("x","Перегрев смартфона увеличивает скорость разряда батареи")))
    def test_distinct_topics_do_not_match(self):
        a=self.rec("a","Роман изучает Python для анализа данных"); b=self.rec("b","Роман изучает английский язык для общения")
        self.assertEqual(analyze_fact_pair(a,b,extract_fact_frame(a),extract_fact_frame(b)).relation,"CONTRADICTION")
    def test_missing_provenance_fails_closed(self):
        self.assertIsNone(extract_fact_frame(self.rec("x","Роман живёт в Германии",None)))
    def test_batch_mapping(self):
        result=extract_fact_frames([self.rec("a","Роман живёт в Германии"),self.rec("b","неподдерживаемая формулировка")])
        self.assertIsNotNone(result["a"]); self.assertIsNone(result["b"])
if __name__=="__main__": unittest.main(verbosity=2)
