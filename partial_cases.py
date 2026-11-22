import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from analysis.execute import evaluate
from database import open_database
from overlap.exchange import export_evidence
from overlap.issue import freeze
from report.publication import publish
from report.store import ReportStore
from review.intake import order
from review.store import OrderStore
from survey.corrections import amend
from survey.intake import record
from survey.store import ObservationStore


ROLES = {"AB": ("B", "A"), "AC": ("C", "A"), "BC": ("C", "B")}
IDENTITY = ["1", "0", "0", "0"]
PROBES = {"B": [1, 0], "C": [0, 1]}
ZERO_PROBES = {"B": [0, 0], "C": [0, 0]}
CASE_MARKERS = {
    "one_common": {
        "A": [("u", 0, 0), ("ab", 2, 0), ("ac", 0, 3)],
        "B": [("u", 0, 0), ("ab", 2, 0), ("bc", 5, 7)],
        "C": [("u", 0, 0), ("ac", 0, 3), ("bc", 5, 7)],
    },
    "two_common": {
        "A": [("u", 0, 0), ("v", 2, 0), ("a_only", 0, 3)],
        "B": [("u", 0, 0), ("v", 2, 0), ("b_only", 0, 3)],
        "C": [("u", 0, 0), ("v", 2, 0), ("c_only", 0, 3)],
    },
    "one_witness_qualifies": {
        "A": [("u", 0, 0), ("v", 1, 0), ("ab1", -2, 0), ("ab2", -4, 0)],
        "B": [("u", 0, 0), ("v", 1, 0), ("ab1", 2, 0), ("ab2", 4, 0),
              ("bc1", 3, 0), ("bc2", 5, 0)],
        "C": [("u", 0, 0), ("v", 1, 0), ("bc1", -3, 0), ("bc2", -5, 0)],
    },
    "half_turn": {
        "A": [("u", -1, 0), ("u", 1, 0), ("v", -2, 0), ("v", 2, 0)],
        "B": [("u", 1, 0), ("v", 2, 0)],
        "C": [("u", -1, 0), ("v", -2, 0)],
    },
}
EXPECTED = {
    "one_common": [],
    "two_common": [[["1", "0"], ["0", "1"]]],
    "one_witness_qualifies": [[["1", "0"], ["0", "1"]]],
    "half_turn": [[["-1", "0"], ["0", "1"]], [["1", "0"], ["0", "-1"]]],
    "half_turn_at_origin": [[["0", "0"], ["0", "0"]]],
}


def require_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def record_case(store, name):
    return {
        station: record(store, name, station, [
            {"category": category, "point": [x, y]} for category, x, y in markers
        ])
        for station, markers in CASE_MARKERS[name].items()
    }


def legacy():
    deliveries = {}
    with open_database(":memory:") as connection:
        observations = ObservationStore(connection)
        observations.initialize()
        for name in ("one_common", "two_common"):
            revisions = record_case(observations, name)
            deliveries[name] = tuple(
                export_evidence(freeze(observations, role, revisions[source], revisions[target]))
                for role, (source, target) in ROLES.items()
            )

    with open_database(":memory:") as connection:
        orders = OrderStore(connection)
        orders.initialize()
        reports = ReportStore(connection)
        reports.initialize()
        for name, pieces in deliveries.items():
            counts = [len(json.loads(text)["body"]["transforms"]) for text in pieces]
            require_equal(counts, [0, 0, 0], name)
            snapshot = publish(reports, evaluate(order(orders, pieces, PROBES), pieces))
            require_equal(snapshot.outcome.status, "no_common_registration", name)
            require_equal(snapshot.outcome.pairs, (), name)
            print(json.dumps({"case": name, "v1_edge_counts": counts,
                              "status": snapshot.outcome.status, "pairs": []}, sort_keys=True))


def endpoint_ids(pieces):
    return {
        endpoint
        for text in pieces
        for candidate in json.loads(text)["body"]["candidates"]
        for match in candidate["matches"]
        for endpoint in match
    }


def partial():
    from overlap.issue import export_partial_links, freeze_partial, open_partial
    from report.export import export_partial
    from report.history import get_partial
    from report.publication import publish_partial

    def issue(observations, revisions):
        handoff = open_partial(observations, revisions)
        pieces = tuple(freeze_partial(observations, handoff, role) for role in ROLES)
        return pieces, export_partial_links(observations, handoff, pieces)

    with TemporaryDirectory() as directory:
        station_path = Path(directory) / "station.sqlite"
        center_path = Path(directory) / "center.sqlite"
        with open_database(station_path) as connection:
            observations = ObservationStore(connection)
            observations.initialize()
            revisions = {name: record_case(observations, name) for name in CASE_MARKERS}
            deliveries = {name: issue(observations, selection)
                          for name, selection in revisions.items()}
            repeated, _ = issue(observations, revisions["two_common"])

        for name in ("one_common", "two_common"):
            pieces, _ = deliveries[name]
            for text in pieces:
                candidates = json.loads(text)["body"]["candidates"]
                require_equal([row["transform"] for row in candidates], [IDENTITY], name)
                require_equal(len(candidates[0]["matches"]), 2, name)

        original, links = deliveries["two_common"]
        require_equal(bool(endpoint_ids(original) & endpoint_ids(repeated)), False,
                      "cross-handoff marker identifiers")
        deliveries["half_turn_at_origin"] = deliveries["half_turn"]
        publications = {}
        with open_database(center_path) as connection:
            OrderStore(connection).initialize()
            reports = ReportStore(connection)
            reports.initialize()
            for name, (pieces, used_links) in deliveries.items():
                probes = ZERO_PROBES if name == "half_turn_at_origin" else PROBES
                snapshot = publish_partial(reports, pieces[::-1], used_links, probes)
                expected_status = "aligned" if EXPECTED[name] else "no_common_registration"
                require_equal(snapshot["pairs"], EXPECTED[name], name)
                require_equal(snapshot["status"], expected_status, name)
                require_equal(snapshot["references"], [json.loads(text)["id"] for text in pieces], name)
                publications[name] = snapshot
            try:
                publish_partial(reports, (repeated[0], *original[1:]), links, PROBES)
            except ValueError:
                pass
            else:
                raise AssertionError("mixed handoff accepted")

        with open_database(station_path) as connection:
            amend(ObservationStore(connection), revisions["two_common"]["A"], [
                {"at": [2, 0], "category": "v", "point": [3, 0]},
            ])
        with open_database(center_path) as connection:
            reports = ReportStore(connection)
            for name, snapshot in publications.items():
                report_id = snapshot["report_id"]
                require_equal(get_partial(reports, report_id), snapshot, name)
                exported = json.loads(export_partial(reports, report_id))
                require_equal(exported, snapshot, name)
                print(json.dumps({"case": name, "collected": exported}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description="Run contour review handoff examples.")
    parser.add_argument("mode", choices=("legacy", "partial"))
    args = parser.parse_args()
    (legacy if args.mode == "legacy" else partial)()


if __name__ == "__main__":
    main()
