from stech_agent.stech.product_reader import ProductReader


class FakeLocator:
    def __init__(self, *, value="", items=None, visible=True): self.value=value; self.items=items or []; self.visible=visible; self.clicked=0
    @property
    def first(self): return self.items[0] if self.items else self
    def nth(self,index): return self.items[index]
    def count(self): return len(self.items) if self.items else (1 if self.visible else 0)
    def click(self): self.clicked += 1
    def input_value(self): return self.value
    def inner_text(self,timeout=None): return self.value
    def wait_for(self,**kwargs): return None
    def locator(self,_css): return FakeLocator(items=[])
    def get_attribute(self,_name): return None


class FakePage:
    def __init__(self):
        self.tabs=[]
        self.roles={("textbox","Ej: Zapatillas Deportivas"):FakeLocator(value="Title SEO"),("textbox","Breve resumen del producto"):FakeLocator(value="Meta description"),("textbox","zapatillas, nike, deporte,"):FakeLocator(value="uno, dos")}
        self.questions=FakeLocator(items=[FakeLocator(value="Q1"),FakeLocator(value="Q2")]); self.answers=FakeLocator(items=[FakeLocator(value="A1"),FakeLocator(value="A2")])
    def get_by_role(self,role,**kwargs):
        name=kwargs.get("name")
        if role=="tab":
            label=getattr(name,"pattern",name); loc=FakeLocator(); original=loc.click
            def click(): self.tabs.append(label); original()
            loc.click=click; return loc
        if role=="textbox" and hasattr(name,"pattern"):
            if "material" in name.pattern.lower(): return self.questions
            if "respuesta" in name.pattern.lower(): return self.answers
        return self.roles.get((role,name),FakeLocator(visible=False))
    def get_by_text(self,*args,**kwargs): return FakeLocator(visible=False)
    def locator(self,*args,**kwargs): return FakeLocator(items=[])
    def wait_for_timeout(self,_ms): return None


def test_reader_visits_only_requested_sections_and_reads_seo():
    page=FakePage(); reader=ProductReader(page,editor_opener=lambda sku,expected_name=None:None)
    state=reader.read_product("PROD-TEST",sections=("seo",))
    assert len(page.tabs)==1 and "SEO" in page.tabs[0]
    assert state.values["seo_title"]=="Title SEO" and state.values["seo_description"]=="Meta description" and state.values["seo_keywords"]=="uno, dos"
    assert state.values["seo_faqs"]==[{"question":"Q1","answer":"A1"},{"question":"Q2","answer":"A2"}]
    assert state.sections==("seo",)


def test_reader_rejects_unknown_section_before_editing():
    called=[]; reader=ProductReader(FakePage(),editor_opener=lambda sku,expected_name=None:called.append(sku))
    try: reader.read_product("PROD-TEST",sections=("unknown",))
    except ValueError as exc: assert "Sección" in str(exc)
    else: raise AssertionError("expected ValueError")
    assert called==[]
