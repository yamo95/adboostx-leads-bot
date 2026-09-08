from copy import deepcopy
import pytest
from leadengine.config import DEFAULTS
from leadengine.db import Database

@pytest.fixture
def cfg(tmp_path):
    c=deepcopy(DEFAULTS);c['base_dir']=str(tmp_path);c['data_dir']=str(tmp_path/'data')
    c['crawl'].update(verify_mx=False,sitemap=False,probe_common_paths=False,delay_seconds=0)
    c['schedule']['enabled']=False
    return c
@pytest.fixture
def db(tmp_path):return Database(tmp_path/'db.sqlite3')
