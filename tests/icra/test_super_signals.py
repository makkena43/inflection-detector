import pytest

pytest.importorskip("pdfplumber")
pytest.importorskip("fitz")  # PyMuPDF; the ICRA scripts need it, the inflection venv does not ship it
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/icra'))
from score_super_signals import score


def test_inclusive_thresholds_and_upgrade_gate():
    evidence={'revenue_growth':{'status':'met','value_pct':25},'order_book':{'status':'met','ratio':2},'capacity_expansion':{'status':'met'},'margin_expansion':{'status':'not_disclosed'},'credit_metrics':{'status':'not_disclosed'}}
    assert score(True,evidence)['classification']=='SUPER_SIGNAL'
    assert score(False,evidence)['classification']=='NOT_SUPER_SIGNAL'
    evidence['revenue_growth']['value_pct']=24.99
    assert score(True,evidence)['classification']=='NOT_SUPER_SIGNAL'


def test_unknown_and_mixed_do_not_inflate_score():
    evidence={'credit_metrics':{'metrics':[{'previous':0.5,'current':0.4,'lower_is_better':True},{'previous':19.4,'current':17.4,'lower_is_better':False}]}}
    result=score(True,evidence)
    assert result['score']==0
    assert result['conditions']['credit_metrics']['status']=='mixed'
    assert result['classification']=='NEEDS_REVIEW'
