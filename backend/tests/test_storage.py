import time

import pytest

from app.storage import LocalStorage, signed_url, verify_signature


def test_local_storage_roundtrip_and_traversal(tmp_path):
    st = LocalStorage(tmp_path)
    st.put("a/b/c.bin", b"123")
    assert st.exists("a/b/c.bin") and st.get("a/b/c.bin") == b"123"
    st.delete("a/b/c.bin")
    assert not st.exists("a/b/c.bin")
    with pytest.raises(ValueError):
        st.put("../../etc/passwd", b"x")
    with pytest.raises(ValueError):
        st.get("/etc/passwd")


def test_signed_urls():
    url = signed_url("inspections/ab/x/original.jpg")
    path, qs = url.split("?")
    params = dict(p.split("=") for p in qs.split("&"))
    key = path.removeprefix("/api/files/")
    assert verify_signature(key, int(params["exp"]), params["sig"])
    assert not verify_signature(key + "x", int(params["exp"]), params["sig"])  # other object
    assert not verify_signature(key, int(params["exp"]) + 1, params["sig"])  # extended expiry
    assert not verify_signature(key, int(time.time()) - 10, params["sig"])  # expired
    assert signed_url(None) is None


def test_s3_storage_against_emulated_s3():
    moto = pytest.importorskip("moto")
    from app.storage import S3Storage

    with moto.mock_aws():
        st = S3Storage("fs-test-bucket", None, "us-east-1", "test", "test")  # creates the bucket when missing
        st.put("inspections/x/original.jpg", b"\xff\xd8jpeg", "image/jpeg")
        assert st.exists("inspections/x/original.jpg") and st.get("inspections/x/original.jpg") == b"\xff\xd8jpeg"
        head = st.client.head_object(Bucket="fs-test-bucket", Key="inspections/x/original.jpg")
        assert head["ContentType"] == "image/jpeg" and head["ServerSideEncryption"] == "AES256"
        st.delete("inspections/x/original.jpg")
        assert not st.exists("inspections/x/original.jpg")
