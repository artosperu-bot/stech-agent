import pytest

from stech_agent.domain.models import FieldPatch
from stech_agent.stech.product_writer import ProductWriter, UnsupportedLiveField
from stech_agent.stech.product_reader import ProductLiveState
from stech_agent.stech.verifier import VerificationResult


def state(**values): return ProductLiveState(sku="PROD-TEST",sections=("basic",),values=values,raw_sections={},verified_at="now")


def test_writer_invokes_only_requested_field_setter_and_saves_once():
    calls=[]; saves=[]; verifies=[]
    writer=ProductWriter(page=object(),editor_opener=lambda sku,expected_name=None:calls.append(("open",sku)),live_reader=lambda sku,fields:state(featured=False,stock="7"),field_setters={"featured":lambda value:calls.append(("featured",value)),"stock":lambda value:calls.append(("stock",value))},saver=lambda:saves.append("save"),verifier=lambda sku,expected:verifies.append((sku,expected)) or VerificationResult(True,{}))
    receipt=writer.update_product_fields("PROD-TEST",FieldPatch({"featured":True}))
    assert calls==[("open","PROD-TEST"),("featured",True)] and saves==["save"] and verifies==[("PROD-TEST",{"featured":True})]
    assert receipt.changed_fields==frozenset({"featured"})


def test_writer_skips_noop_fields():
    calls=[]; writer=ProductWriter(page=object(),editor_opener=lambda sku,expected_name=None:calls.append("open"),live_reader=lambda sku,fields:state(stock="7"),field_setters={"stock":lambda value:calls.append("set")},saver=lambda:calls.append("save"),verifier=lambda sku,expected:VerificationResult(True,{}))
    receipt=writer.update_product_fields("PROD-TEST",FieldPatch({"stock":7}))
    assert calls==["open"] and receipt.changed_fields==frozenset() and receipt.status=="NOOP"


def test_unknown_or_unsupported_field_fails_before_opening_editor():
    calls=[]; writer=ProductWriter(page=object(),editor_opener=lambda sku,expected_name=None:calls.append("open"),live_reader=lambda sku,fields:state(),field_setters={"stock":lambda value:None},saver=lambda:None,verifier=lambda sku,expected:VerificationResult(True,{}))
    with pytest.raises(UnsupportedLiveField,match="description"): writer.update_product_fields("PROD-TEST",FieldPatch({"description":"x"}))
    assert calls==[]


def test_verification_failure_returns_review_not_success():
    writer=ProductWriter(page=object(),editor_opener=lambda sku,expected_name=None:None,live_reader=lambda sku,fields:state(stock="5"),field_setters={"stock":lambda value:None},saver=lambda:None,verifier=lambda sku,expected:VerificationResult(False,{"stock":object()}))
    assert writer.update_product_fields("PROD-TEST",FieldPatch({"stock":6})).status=="REVIEW"
