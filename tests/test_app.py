from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_demo_dashboard_and_in_transit_filter():
    app = AppTest.from_file(APP).run(timeout=30)
    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Total Shipments"] == "158"
    assert metrics["Cost Anomalies"] == "4"
    assert metrics["On-Time Delivery Rate"] == "47.8%"
    status_filter = next(widget for widget in app.multiselect if widget.label == "Shipment status")
    status_filter.set_value(["In Transit"]).run(timeout=30)
    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Delivered Shipments"] == "0"
    assert metrics["On-Time Delivery Rate"] == "N/A"
    assert metrics["Average Delay Hours"] == "N/A"


def test_no_matching_filter_and_upload_empty_state():
    app = AppTest.from_file(APP).run(timeout=30)
    search = next(widget for widget in app.text_input if widget.label == "Shipment ID contains")
    search.set_value("DOES-NOT-EXIST").run(timeout=30)
    assert not app.exception
    assert app.metric[0].value == "0"
    assert any("No records match" in warning.value for warning in app.warning)
    app.radio[0].set_value("Upload a file").run(timeout=30)
    assert not app.exception
    assert any("Upload a CSV or Excel" in message.value for message in app.info)
