from stech_agent.stech import product_writer

class Box:
    def __init__(self, value=""):
        self.value = value
    def fill(self, value):
        self.value = str(value)
    def input_value(self):
        return self.value

class Collection:
    def __init__(self, values=()):
        self.items = [Box(v) for v in values]
    def count(self):
        return len(self.items)
    def nth(self, index):
        return self.items[index]

class Button:
    def __init__(self, callback=None):
        self.callback = callback
        self.clicks = 0
    def click(self):
        self.clicks += 1
        if self.callback:
            self.callback()

def test_faq_writer_adds_missing_slots_and_fills_three(monkeypatch):
    questions = Collection(["Q manual"])
    answers = Collection(["A manual"])
    def add_slot():
        questions.items.append(Box())
        answers.items.append(Box())
    add = Button(add_slot)
    tab = Button()
    def fake_locate(page, key):
        return {"tab_seo": tab, "seo_question": questions, "seo_answer": answers, "seo_add_faq": add}[key]
    monkeypatch.setattr(product_writer, "locate", fake_locate)
    desired = [
        {"question":"Q manual","answer":"A manual"},
        {"question":"Q2","answer":"A2"},
        {"question":"Q3","answer":"A3"},
    ]
    product_writer._set_seo_faqs(object(), desired)
    assert add.clicks == 2
    assert [x.value for x in questions.items[:3]] == ["Q manual", "Q2", "Q3"]
    assert [x.value for x in answers.items[:3]] == ["A manual", "A2", "A3"]

def test_faq_reader_returns_three_pairs(monkeypatch):
    questions = Collection(["Q1", "Q2", "Q3"])
    answers = Collection(["A1", "A2", "A3"])
    tab = Button()
    def fake_locate(page, key):
        return {"tab_seo": tab, "seo_question": questions, "seo_answer": answers}[key]
    monkeypatch.setattr(product_writer, "locate", fake_locate)
    assert product_writer._read_seo_faqs(object()) == [
        {"question":"Q1","answer":"A1"},
        {"question":"Q2","answer":"A2"},
        {"question":"Q3","answer":"A3"},
    ]
