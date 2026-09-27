```python
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pathlib import Path
from pydantic import BaseModel
import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent


def get_connection():
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        sslmode="require",
    )


FAULTS = [
    ("Conveyor", "Frame Coating Fault - MS"),
    ("Conveyor", "Leg / patti spot broken"),
    ("Conveyor", "Frame Dent"),
    ("Conveyor", "Rubber Leg Fault"),
    ("Conveyor", "Dial Plate Sticker Damage"),
    ("Conveyor", "Dial Plate Scratches / printing issues"),
    ("Conveyor", "Knob Scratches / printing issues"),
    ("Conveyor", "Glass Broken"),
    ("Conveyor", "Glass Acid mark / Printing issue"),
    ("Conveyor", "O Ring Fault"),
    ("Conveyor", "Fixed Tray - Small"),
    ("Conveyor", "Fixed Tray - Big"),
    ("Conveyor", "Fixed Tray - Jumbo"),
    ("Conveyor", "Bundy Tube Damage"),
    ("Conveyor", "Bundy Tube Leak"),
    ("Process", "Mixing Tube Fault - Small"),
    ("Process", "Mixing Tube Fault - Big"),
    ("Process", "Mixing Tube Fault - Jumbo"),
    ("Process", "Mixing Tube Broken"),
    ("Process", "Sim OFF"),
    ("Process", "Sim HIGH"),
    ("Process", "Function Tight"),
    ("Process", "Flame LOW"),
    ("Process", "Flame HIGH"),
    ("Process", "Jet Block"),
    ("Process", "Pipe Block"),
    ("Process", "Burner Fault (W/O Pin)"),
    ("Process", "Burner Fault (I/O Flame)"),
    ("Process", "Burner Coating Fault"),
    ("Process", "Panstand Rejection - Seating / Bend"),
    ("Process", "Panstand Rejection - Coating fault"),
    ("Process", "Panstand Rejection - Pin removed"),
    ("Process", "PC Box Damage"),
    ("Process", "PC Box Vendor Rejection"),
    ("Process", "Dry Air Leak Testing"),
]

FAULT_TO_SECTION = {
    fault_name: section
    for section, fault_name in FAULTS
}


def create_production_table():
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS production_register (
                    id SERIAL PRIMARY KEY,
                    report_date DATE NOT NULL,
                    shift VARCHAR(50) NOT NULL,
                    model_name VARCHAR(200) NOT NULL,
                    production_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(report_date, shift, model_name)
                )
            """)

        conn.commit()

    finally:
        conn.close()


@app.on_event("startup")
def startup_event():
    create_production_table()


class RejectionItem(BaseModel):
    fault_name: str
    supplier: int = 0
    process: int = 0


class ProductionItem(BaseModel):
    model_name: str
    production_count: int = 0


class RejectionData(BaseModel):
    report_date: str
    shift: str
    data: list[RejectionItem] = []
    production: list[ProductionItem] = []


@app.get("/", response_class=HTMLResponse)
def home():
    html_path = BASE_DIR / "templates" / "index.html"
    return html_path.read_text(encoding="utf-8")


@app.get("/rejections")
def get_rejections(report_date: str, shift: str):
    conn = get_connection()

    try:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    fault_name,
                    supplier_rejection,
                    process_rejection
                FROM rejection_register
                WHERE report_date = %s
                  AND shift = %s
            """, (report_date, shift))

            rows = cur.fetchall()

            saved_data = {
                row[0]: {
                    "supplier": row[1] or 0,
                    "process": row[2] or 0
                }
                for row in rows
            }

            result = []

            for section, fault_name in FAULTS:

                values = saved_data.get(
                    fault_name,
                    {
                        "supplier": 0,
                        "process": 0
                    }
                )

                result.append({
                    "fault_name": fault_name,
                    "supplier": values["supplier"],
                    "process": values["process"]
                })

            return {
                "success": True,
                "data": result
            }

    finally:
        conn.close()


@app.get("/production")
def get_production(report_date: str, shift: str):
    conn = get_connection()

    try:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    model_name,
                    production_count
                FROM production_register
                WHERE report_date = %s
                  AND shift = %s
                ORDER BY id
            """, (report_date, shift))

            rows = cur.fetchall()

            result = [
                {
                    "model_name": row[0],
                    "production_count": row[1] or 0
                }
                for row in rows
            ]

            return {
                "success": True,
                "data": result
            }

    finally:
        conn.close()


@app.post("/save")
def save_data(payload: RejectionData):
    conn = get_connection()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                DELETE FROM rejection_register
                WHERE report_date = %s
                  AND shift = %s
            """, (
                payload.report_date,
                payload.shift
            ))


            for item in payload.data:

                supplier = item.supplier or 0
                process = item.process or 0

                if supplier == 0 and process == 0:
                    continue

                section = FAULT_TO_SECTION.get(
                    item.fault_name,
                    "Process"
                )

                cur.execute("""
                    INSERT INTO rejection_register
                    (
                        report_date,
                        shift,
                        section,
                        fault_name,
                        supplier_rejection,
                        process_rejection
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    payload.report_date,
                    payload.shift,
                    section,
                    item.fault_name,
                    supplier,
                    process
                ))


            cur.execute("""
                DELETE FROM production_register
                WHERE report_date = %s
                  AND shift = %s
            """, (
                payload.report_date,
                payload.shift
            ))


            for item in payload.production:

                count = item.production_count or 0

                if count <= 0:
                    continue

                cur.execute("""
                    INSERT INTO production_register
                    (
                        report_date,
                        shift,
                        model_name,
                        production_count
                    )
                    VALUES (%s, %s, %s, %s)
                """, (
                    payload.report_date,
                    payload.shift,
                    item.model_name,
                    count
                ))

        conn.commit()

        return {
            "success": True,
            "message": "Data saved successfully"
        }

    except Exception as e:

        conn.rollback()

        return {
            "success": False,
            "message": str(e)
        }

    finally:
        conn.close()


@app.get("/daily-total")
def daily_total(report_date: str):

    conn = get_connection()

    try:

        with conn.cursor() as cur:

            # Overall rejection
            cur.execute("""
                SELECT
                    COALESCE(SUM(supplier_rejection), 0),
                    COALESCE(SUM(process_rejection), 0)
                FROM rejection_register
                WHERE report_date = %s
            """, (report_date,))

            rejection_row = cur.fetchone()

            supplier_total = rejection_row[0] or 0
            process_total = rejection_row[1] or 0
            rejection_total = supplier_total + process_total


            # Overall production
            cur.execute("""
                SELECT
                    COALESCE(SUM(production_count), 0)
                FROM production_register
                WHERE report_date = %s
            """, (report_date,))

            production_row = cur.fetchone()

            production_total = production_row[0] or 0


            # ALL fault rows
            rejection_by_fault = []

            for section, fault_name in FAULTS:

                cur.execute("""
                    SELECT
                        COALESCE(SUM(supplier_rejection), 0),
                        COALESCE(SUM(process_rejection), 0)
                    FROM rejection_register
                    WHERE report_date = %s
                      AND fault_name = %s
                """, (
                    report_date,
                    fault_name
                ))

                row = cur.fetchone()

                supplier = row[0] or 0
                process = row[1] or 0

                rejection_by_fault.append({
                    "fault_name": fault_name,
                    "supplier": supplier,
                    "process": process,
                    "total": supplier + process
                })


            # Shift-wise production
            cur.execute("""
                SELECT
                    shift,
                    COALESCE(SUM(production_count), 0)
                FROM production_register
                WHERE report_date = %s
                GROUP BY shift
            """, (report_date,))

            shift_rows = cur.fetchall()

            shift_order = {
                "1st Shift": 1,
                "General Shift": 2,
                "2nd Shift": 3
            }

            production_by_shift = [
                {
                    "shift": row[0],
                    "production": row[1] or 0
                }
                for row in shift_rows
            ]

            production_by_shift.sort(
                key=lambda x: shift_order.get(
                    x["shift"],
                    99
                )
            )


            # Model-wise production
            cur.execute("""
                SELECT
                    model_name,
                    COALESCE(SUM(production_count), 0)
                FROM production_register
                WHERE report_date = %s
                GROUP BY model_name
                ORDER BY model_name
            """, (report_date,))

            model_rows = cur.fetchall()

            production_by_model = [
                {
                    "model_name": row[0],
                    "production": row[1] or 0
                }
                for row in model_rows
            ]


            return {
                "success": True,
                "report_date": report_date,
                "production_total": production_total,
                "supplier_total": supplier_total,
                "process_total": process_total,
                "rejection_total": rejection_total,
                "rejection_by_fault": rejection_by_fault,
                "production_by_shift": production_by_shift,
                "production_by_model": production_by_model
            }

    finally:
        conn.close()


@app.delete("/delete")
def delete_data(report_date: str, shift: str):

    conn = get_connection()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                DELETE FROM rejection_register
                WHERE report_date = %s
                  AND shift = %s
            """, (
                report_date,
                shift
            ))

            cur.execute("""
                DELETE FROM production_register
                WHERE report_date = %s
                  AND shift = %s
            """, (
                report_date,
                shift
            ))

        conn.commit()

        return {
            "success": True,
            "message": "Data deleted successfully"
        }

    except Exception as e:

        conn.rollback()

        return {
            "success": False,
            "message": str(e)
        }

    finally:
        conn.close()
```

**`templates/index.html` முழுவதையும் replace செய்யுங்கள்:**

```html
<!DOCTYPE html>
<html lang="en">

<head>

    <meta charset="UTF-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1.0">

    <title>GTS QC Rejection Report</title>


    <style>

        * {
            box-sizing: border-box;
        }


        body {
            margin: 0;
            padding: 15px;
            font-family: Arial, sans-serif;
            background: #f4f4f4;
            color: #222;
        }


        .container {
            max-width: 1200px;
            margin: auto;
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.08);
        }


        h1 {
            text-align: center;
            margin-top: 0;
            margin-bottom: 20px;
        }


        h2 {
            margin-top: 25px;
            margin-bottom: 12px;
            font-size: 20px;
        }


        .controls {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 20px;
        }


        .controls label {
            font-weight: bold;
            display: flex;
            flex-direction: column;
            gap: 5px;
        }


        input,
        select {
            min-height: 40px;
            padding: 8px 10px;
            border: 1px solid #bbb;
            border-radius: 6px;
            font-size: 15px;
        }


        .table-wrapper {
            width: 100%;
            overflow-x: auto;
        }


        table {
            width: 100%;
            border-collapse: collapse;
        }


        th,
        td {
            border: 1px solid #ccc;
            padding: 8px;
            text-align: center;
        }


        th {
            background: #eeeeee;
            font-weight: bold;
        }


        td:first-child,
        th:first-child {
            text-align: left;
        }


        .rejection-input {
            width: 80px;
            text-align: center;
        }


        .model-name-input {
            width: 100%;
            min-width: 150px;
        }


        .count-input {
            width: 120px;
            text-align: center;
        }


        .action-buttons {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-top: 20px;
        }


        button {
            min-height: 42px;
            padding: 10px 16px;
            border: none;
            border-radius: 7px;
            background: #333;
            color: white;
            font-size: 15px;
            font-weight: bold;
            cursor: pointer;
        }


        button:hover {
            opacity: 0.9;
        }


        .add-model-btn {
            margin-top: 10px;
            background: #333;
        }


        .message {
            margin-top: 15px;
            padding: 10px;
            border-radius: 6px;
            display: none;
            font-weight: bold;
        }


        .success {
            background: #dff0d8;
            color: #2e6b2e;
        }


        .error {
            background: #f8d7da;
            color: #842029;
        }


        .daily-section {
            margin-top: 30px;
            display: none;
        }


        .daily-date-selector {
            display: flex;
            align-items: end;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }


        .daily-date-selector label {
            display: flex;
            flex-direction: column;
            gap: 5px;
            font-weight: bold;
        }


        .daily-date-selector input {
            min-height: 42px;
        }


        .summary-cards {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
            margin-bottom: 20px;
        }


        .summary-card {
            border: 1px solid #ccc;
            border-radius: 8px;
            padding: 15px;
            text-align: center;
            background: #fafafa;
        }


        .summary-card h3 {
            margin: 0 0 8px;
            font-size: 15px;
        }


        .summary-card p {
            margin: 0;
            font-size: 24px;
            font-weight: bold;
        }


        .section-title {
            margin-top: 25px;
        }


        .loading {
            text-align: center;
            padding: 15px;
            display: none;
        }


        /* Day Total fault table */

        #faultWiseBody td:first-child,
        #faultWiseBody th:first-child {
            width: 55%;
            max-width: 55%;
            white-space: normal;
            word-break: normal;
            overflow-wrap: break-word;
            text-align: left;
        }


        #faultWiseBody td:not(:first-child),
        #faultWiseBody th:not(:first-child) {
            width: 15%;
            white-space: nowrap;
            text-align: center;
        }


        @media (max-width: 700px) {

            body {
                padding: 8px;
            }


            .container {
                padding: 12px;
            }


            h1 {
                font-size: 22px;
            }


            h2 {
                font-size: 18px;
            }


            .controls {
                flex-direction: column;
            }


            .controls label {
                width: 100%;
            }


            .controls input,
            .controls select {
                width: 100%;
            }


            .summary-cards {
                grid-template-columns: repeat(2, 1fr);
            }


            .action-buttons {
                flex-direction: column;
            }


            .action-buttons button {
                width: 100%;
            }


            .add-model-btn {
                width: 100%;
                min-height: 46px;
            }


            .daily-date-selector {
                flex-direction: column;
                align-items: stretch;
            }


            .daily-date-selector label,
            .daily-date-selector input,
            .daily-date-selector button {
                width: 100%;
            }


            /* Compact mobile Day Total table */

            #faultWiseBody td:first-child,
            #faultWiseBody th:first-child {
                width: 48%;
                max-width: 48%;
                padding: 6px 5px;
                font-size: 13px;
                line-height: 1.25;
            }


            #faultWiseBody td:not(:first-child),
            #faultWiseBody th:not(:first-child) {
                width: 17.3%;
                padding: 6px 3px;
                font-size: 13px;
            }

        }

    </style>

</head>


<body>


<div class="container">


    <h1>GTS QC Rejection Report</h1>


    <!-- DATE AND SHIFT -->

    <div class="controls">

        <label>

            Report Date

            <input
                type="date"
                id="reportDate">

        </label>


        <label>

            Shift

            <select id="shift">

                <option value="1st Shift">
                    1st Shift
                </option>

                <option value="General Shift">
                    General Shift
                </option>

                <option value="2nd Shift">
                    2nd Shift
                </option>

            </select>

        </label>

    </div>


    <!-- REJECTION DETAILS -->

    <h2>Rejection Details</h2>


    <div class="table-wrapper">

        <table>

            <thead>

                <tr>

                    <th>
                        Fault Name
                    </th>

                    <th>
                        Supplier
                    </th>

                    <th>
                        Process
                    </th>

                </tr>

            </thead>


            <tbody id="rejectionBody"></tbody>

        </table>

    </div>


    <!-- PRODUCTION DETAILS -->

    <h2>Production Details</h2>


    <div class="table-wrapper">

        <table>

            <thead>

                <tr>

                    <th>
                        Model Name
                    </th>

                    <th>
                        Production Count
                    </th>

                </tr>

            </thead>


            <tbody id="productionBody"></tbody>

        </table>

    </div>


    <!-- ADD MODEL -->

    <button
        type="button"
        class="add-model-btn"
        onclick="addProductionRow()">

        + Add Model

    </button>


    <!-- ACTION BUTTONS -->

    <div class="action-buttons">

        <button
            type="button"
            onclick="saveData()">

            Save

        </button>


        <button
            type="button"
            onclick="showDailyTotal()">

            Daily Total

        </button>


        <button
            type="button"
            onclick="downloadShift()">

            Download Shift

        </button>


        <button
            type="button"
            onclick="downloadDay()">

            Download Day

        </button>


        <button
            type="button"
            onclick="deleteData()">

            Delete Date + Shift

        </button>

    </div>


    <div
        id="message"
        class="message">
    </div>


    <div
        id="loading"
        class="loading">

        Loading...

    </div>


    <!-- DAILY TOTAL -->

    <div
        id="dailySection"
        class="daily-section">


        <h2>
            Daily Total
        </h2>


        <!-- DAILY TOTAL DATE SELECT -->

        <div class="daily-date-selector">

            <label>

                Daily Total Date

                <input
                    type="date"
                    id="dailyTotalDate">

            </label>


            <button
                type="button"
                onclick="showDailyTotal()">

                View Daily Total

            </button>

        </div>


        <!-- SUMMARY CARDS -->

        <div class="summary-cards">


            <div class="summary-card">

                <h3>
                    Total Production
                </h3>

                <p id="totalProduction">
                    0
                </p>

            </div>


            <div class="summary-card">

                <h3>
                    Supplier Rejection
                </h3>

                <p id="totalSupplier">
                    0
                </p>

            </div>


            <div class="summary-card">

                <h3>
                    Process Rejection
                </h3>

                <p id="totalProcess">
                    0
                </p>

            </div>


            <div class="summary-card">

                <h3>
                    Total Rejection
                </h3>

                <p id="totalRejection">
                    0
                </p>

            </div>


        </div>


        <!-- FAULT-WISE -->

        <h2 class="section-title">

            Fault-wise Rejection

        </h2>


        <div class="table-wrapper">

            <table>

                <thead>

                    <tr>

                        <th>
                            Fault Name
                        </th>

                        <th>
                            Supplier
                        </th>

                        <th>
                            Process
                        </th>

                        <th>
                            Total
                        </th>

                    </tr>

                </thead>


                <tbody id="faultWiseBody"></tbody>

            </table>

        </div>


        <!-- SHIFT-WISE -->

        <h2 class="section-title">

            Shift-wise Production

        </h2>


        <div class="table-wrapper">

            <table>

                <thead>

                    <tr>

                        <th>
                            Shift
                        </th>

                        <th>
                            Production
                        </th>

                    </tr>

                </thead>


                <tbody id="shiftWiseBody"></tbody>

            </table>

        </div>


        <!-- MODEL-WISE -->

        <h2 class="section-title">

            Model-wise Production

        </h2>


        <div class="table-wrapper">

            <table>

                <thead>

                    <tr>

                        <th>
                            Model Name
                        </th>

                        <th>
```
