import csv
import io
from typing import Any


def rows_to_csv(columns: list[dict[str, str]], rows: list[dict[str, Any]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=[column["name"] for column in columns], extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({
            key: "" if value is None else value
            for key, value in row.items()
        })
    return output.getvalue()
