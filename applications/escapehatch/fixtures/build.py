"""Regenerate the committed .ods and .csv fixtures from escapehatch.ods."""

from pathlib import Path

from escapehatch.ods import expected_csv, write_ods

HERE = Path(__file__).resolve().parent


def main() -> None:
    write_ods(HERE / "ops-hold-log.ods")
    (HERE / "ops-hold-log.csv").write_text(expected_csv(), encoding="utf-8")
    print("wrote", HERE / "ops-hold-log.ods")
    print("wrote", HERE / "ops-hold-log.csv")


if __name__ == "__main__":
    main()
