from app.answering.safety import check_output, check_request


def test_certification_request_blocked():
    assert check_request("Hãy xác nhận đạt chuẩn cho tòa nhà này") is not None
    assert check_request("Please CERTIFY this building") is not None


def test_final_equipment_blocked():
    assert check_request("Cho tôi bố trí cuối cùng của bình chữa cháy") is not None


def test_real_emergency_blocked():
    assert check_request("Nhà tôi đang cháy thật, đang có cháy!") is not None
    assert check_request("There is a fire now") is not None


def test_normal_question_allowed():
    assert check_request("Lối thoát hiểm nên bố trí thế nào?") is None


def test_word_boundary():
    assert check_request("uncertified") is None


def test_output_certification_phrase_blocked():
    assert check_output("Công trình đã ĐẠT CHUẨN PCCC.") is not None
    assert check_output("This design is compliant") is not None
    assert check_output("Cần kiểm tra lại lối thoát hiểm.") is None
