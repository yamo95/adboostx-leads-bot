from leadengine.sheets import raw_cell, column_label

def test_sheets_raw_values_preserve_literals():
    assert raw_cell('+972501234567') == '+972501234567'
    assert raw_cell('=literal') == '=literal'
    assert raw_cell(None) == ''
    assert raw_cell('a\x00b') == 'ab'
    assert raw_cell({'evidence':True}) == '{"evidence": true}'

def test_clear_range_column_is_bounded():
    assert column_label(1) == 'A'
    assert column_label(26) == 'Z'
    assert column_label(27) == 'AA'
    assert column_label(52) == 'AZ'
