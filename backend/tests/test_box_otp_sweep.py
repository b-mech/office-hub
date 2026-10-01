from types import SimpleNamespace

from app.services.box_otp_sweep import BoxOtpCandidate
from app.services.box_otp_sweep import BoxOtpSweepService
from app.services.box_otp_sweep import SUPPORTED_EXTENSIONS
from app.services.box_otp_sweep import classify_box_otp_filename


def candidate(*, file_id: str, path: str, sha1: str = "same") -> BoxOtpCandidate:
    return BoxOtpCandidate(
        file_id=file_id,
        name=path.rsplit("/", 1)[-1],
        path=path,
        sha1=sha1,
        size=100,
        classification="land_otp",
        matched_queries=("OTP",),
    )


def test_classification_distinguishes_land_sale_supporting_and_ambiguous() -> None:
    assert classify_box_otp_filename("1D - OTP (Land) - 48 Woodland Way.pdf") == "land_otp"
    assert classify_box_otp_filename("1D - OTP (Sale) - 48 Woodland Way.pdf") == "sale_otp"
    assert classify_box_otp_filename("OTP Land Amendment - 48 Woodland Way.pdf") == "supporting"
    assert classify_box_otp_filename("Offer to Purchase.pdf") == "other"


def test_selected_copy_wins_exact_binary_group() -> None:
    service = object.__new__(BoxOtpSweepService)
    master = candidate(file_id="master", path="Production/z - Files/OTP (Land).pdf")
    selected = candidate(file_id="selected", path="Production/48 Woodland/OTP (Land).pdf")

    representatives = service._select_representatives([master, selected], {"selected"})

    assert representatives["same"].file_id == "selected"


def test_master_copy_wins_when_no_copy_is_selected() -> None:
    service = object.__new__(BoxOtpSweepService)
    master = candidate(file_id="master", path="Production/z - Files/OTP (Land).pdf")
    property_copy = candidate(file_id="copy", path="Production/48 Woodland/OTP (Land).pdf")

    representatives = service._select_representatives([property_copy, master], set())

    assert representatives["same"].file_id == "master"


def test_search_is_restricted_to_supported_filenames() -> None:
    calls: list[dict[str, object]] = []

    class Search:
        def query(self, **kwargs):
            calls.append(kwargs)
            return []

    class Client:
        def folder(self, folder_id: str):
            return SimpleNamespace(id=folder_id)

        def search(self):
            return Search()

    service = object.__new__(BoxOtpSweepService)
    service._production_folder_id = "production"
    service._client = Client()

    assert service._search_candidates(("OTP",)) == []
    assert calls[0]["content_types"] == ["name"]
    assert calls[0]["file_extensions"] == sorted(SUPPORTED_EXTENSIONS)
