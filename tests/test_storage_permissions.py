from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.storage import JsonStore


def append_performance_in_process(root: str, index: int) -> None:
    JsonStore(Path(root)).append_performance(
        {
            "record": {
                "content_id": f"parallel-content-{index}",
                "review_window": "72h",
            },
            "action": "wait_for_more_data",
            "reason": "storage concurrency test",
        }
    )


class StorageConcurrencyAndPermissionTests(unittest.TestCase):
    def test_state_and_audit_writes_flush_to_stable_storage(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "marketing_machine.storage.os.fsync", wraps=os.fsync
        ) as fsync:
            store = JsonStore(Path(tmp))
            store.save_state(
                {
                    "brief": {
                        "id": "durability-state",
                        "campaign": "K1",
                        "status": "needs_human_review",
                    }
                }
            )
            state_sync_calls = fsync.call_count
            store.append_event("durability_audit", {"safe": True})

        self.assertGreaterEqual(state_sync_calls, 1)
        self.assertGreater(fsync.call_count, state_sync_calls)

    def test_different_key_process_writes_keep_shared_jsonl_parseable(self):
        with tempfile.TemporaryDirectory() as tmp:
            with ProcessPoolExecutor(max_workers=4) as pool:
                list(pool.map(append_performance_in_process, [tmp] * 64, range(64)))

            lines = (Path(tmp) / "performance" / "records.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            records = [json.loads(line) for line in lines if line.strip()]

        self.assertEqual(len(records), 64)
        self.assertEqual(
            {item["record"]["content_id"] for item in records},
            {f"parallel-content-{index}" for index in range(64)},
        )

    def test_parallel_event_appends_are_complete_and_parseable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            with ThreadPoolExecutor(max_workers=16) as pool:
                list(
                    pool.map(
                        lambda index: store.append_event(
                            "parallel_events", {"index": index}
                        ),
                        range(256),
                    )
                )
            lines = (Path(tmp) / "events" / "parallel_events.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            records = [json.loads(line) for line in lines if line.strip()]

        self.assertEqual(len(records), 256)
        self.assertEqual({item["index"] for item in records}, set(range(256)))

    @unittest.skipIf(os.name == "nt", "POSIX mode bits are verified in the Linux runtime")
    def test_runtime_directories_and_data_files_are_private_on_posix(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore()
            event_path = store.append_event("permission_check", {"safe": True})
            state = {
                "brief": {
                    "id": "permission-state",
                    "campaign": "K1",
                    "status": "needs_human_review",
                }
            }
            state_path = store.save_state(state)

            self.assertEqual(Path(tmp).stat().st_mode & 0o777, 0o700)
            self.assertEqual((Path(tmp) / "events").stat().st_mode & 0o777, 0o700)
            self.assertEqual(event_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
