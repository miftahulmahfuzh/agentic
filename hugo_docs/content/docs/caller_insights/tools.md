---
title: "Tools Documentation"
date: 2025-09-10
draft: false
---

This document provides a detailed overview of all the tools available to the agent. Each tool's purpose, input arguments, output format, and internal logic are described to aid in understanding, debugging, and future development.

---

## Tool: `get_current_time`

> Use this tool if user ask about the current time. It takes no arguments.

-   **Purpose:** To provide the agent with the current server time and date, including timezone information. This is essential for grounding any time-sensitive queries.
-   **Input Arguments:** None. The tool is called with an empty JSON object.
    ```json
    {}
    ```
-   **Output Format:** A single string representing the current time in [RFC3339](https://www.rfc-editor.org/rfc/rfc3339) format.
    ```
    "2023-10-27T10:30:00+07:00"
    ```
-   **Logic / Algorithm:**
    1.  Calls `time.Now()` to get the current system time.
    2.  Formats the time object into an RFC3339 string.
    3.  Returns the formatted string.

---

## Tool: `news_summary`

> Use this tool to get the latest 5 news articles for a given stock. The 'input' parameter should be the 4-letter stock code, for example: "BBCA".

-   **Purpose:** To retrieve recent news headlines and summaries for a specific publicly traded company.
-   **Input Arguments:**
    ```json
    {
      "type": "object",
      "properties": {
        "code": {
          "type": "string",
          "description": "The 4-letter stock code, for example: BBCA"
        }
      },
      "required": ["code"]
    }
    ```
-   **Output Format:** A plain text string where each news article is formatted with its title, date, and summary, separated by double newlines. If no news is found, it returns a specific message.
    ```text
    Title: Bank Central Asia Reports Strong Q3 Earnings
    Date: 2023-10-26
    Summary: BBCA announced a 15% year-over-year increase in net profit, driven by strong loan growth and improved net interest margins.

    Title: Tech Sector Sees Volatility Amid Global Concerns
    Date: 2023-10-25
    Summary: Stocks like BBCA remained resilient while the broader tech index faced a downturn due to international market pressures.
    ```
-   **Logic / Algorithm:**
    1.  The input stock `code` is converted to uppercase.
    2.  It checks if the news service URL is configured in the application settings.
    3.  A JSON payload `{"secCodes": ["<CODE>"]}` is constructed.
    4.  A `POST` request is made to the backend news API with a 30-second timeout.
    5.  It handles various errors, including context cancellation (user abort), timeouts, and network failures.
    6.  The API response is read. If the status code is not `200 OK`, an error is returned.
    7.  The JSON response is parsed. It expects a structure containing a list of news items.
    8.  If the API reports a non-success message or the list of news is empty, it returns a user-friendly "No news found for `<CODE>`" message.
    9.  It iterates through the top 5 news items from the response.
    10. For each item, it extracts the title, publication date (ignoring the time part), and the LLM-generated summary.
    11. These pieces are formatted into the final text string and returned.

---

## Tool: `realtime_market`

> Gets the CURRENT, LIVE market data for a stock. Use this ONLY for the price 'right now' or the 'latest' single price point. This tool provides a real-time snapshot. DO NOT use this for questions about trends, history, or any period of time (e.g., 'last week', 'past month').

-   **Purpose:** To fetch a real-time snapshot of market data for one or more stocks. This includes the latest price, change, volume, and other key daily metrics.
-   **Input Arguments:**
    ```json
    {
      "type": "object",
      "properties": {
        "codes": {
          "type": "array",
          "items": {"type": "string"},
          "description": "A list of 4-letter stock codes, e.g., [\"BBCA\", \"GOTO\"]"
        }
      },
      "required": ["codes"]
    }
    ```
-   **Output Format:** A series of JSON objects, one for each requested stock, separated by newlines. If data for a specific stock cannot be found, an error object is returned for that stock.
    ```json
    {"code":"BBCA","date":"2023-10-27","time":"11:15","last price":9100,"change":-25,"change%":"-0.27%","previous close price":9125,"open price":9125,"high price":9150,"low price":9075,"value":"1.2 T","volume":"131.9 M","Average Price":9105.5,"Frequency":"15,789"}
    {"code": "INVALID", "error": "No data found"}
    ```
-   **Logic / Algorithm:**
    1.  It checks if the input `codes` list is empty.
    2.  All stock codes in the list are converted to uppercase.
    3.  A single `POST` request is made to the backend's price summary API with the list of codes.
    4.  The API response, which contains a list of data for all found stocks, is processed. The results are placed into a map for efficient lookup (`code` -> `data`).
    5.  The tool then iterates through the *original list of requested codes*.
    6.  For each code, it looks it up in the results map.
    7.  If found, it formats the raw data into a structured `FormattedMarketData` object. This includes formatting large numbers (like `value` and `volume`) into human-readable strings (e.g., "1.2 T").
    8.  If a code is not found in the map, a specific JSON error object for that code is generated.
    9.  Each resulting JSON object (either data or error) is appended to a string, separated by newlines.

---

## Tool: `historical_marketdata`

> Gets HISTORICAL data for a stock's performance OVER A PERIOD OF TIME. This is ESSENTIAL for analyzing trends, charts, and price movements between a start and end date. Use this for ANY query that involves a date range like 'last week', 'past year', 'daily movement', 'since January', etc.

-   **Purpose:** To retrieve historical end-of-day trading data for a stock over a specified period and aggregate it by a given time granularity.
-   **Input Arguments:**
    ```json
    {
      "type": "object",
      "properties": {
        "code": {"type": "string", "description": "The stock ticker symbol."},
        "start_date": {"type": "string", "description": "Start date in 'YYYY-MM-DD' format."},
        "end_date": {"type": "string", "description": "End date in 'YYYY-MM-DD' format."},
        "granularity": {
          "type": "string",
          "description": "Time interval for aggregation.",
          "enum": ["daily", "weekly", "monthly", "quarterly", "yearly"]
        }
      },
      "required": ["code", "start_date", "end_date", "granularity"]
    }
    ```
-   **Output Format:** A JSON array of objects. The structure of the objects depends on the requested `granularity`.
    -   **For `granularity: "daily"`:**
        ```json
        [
          { "date": "2023-10-26", "close price": 9125, "change": -25, "change%": -0.27, "volume": 150000000 },
          { "date": "2023-10-25", "close price": 9150, "change": 50, "change%": 0.55, "volume": 120000000 }
        ]
        ```
    -   **For aggregated granularities (e.g., `"weekly"`):**
        ```json
        [
          { "period_identifier": "2023-W43", "start_date_of_period": "2023-10-23", "end_date_of_period": "2023-10-26", "period_end_close_price": 9125, "period_change": -75, "period_change_percentage": -0.82 },
          { "period_identifier": "2023-W42", "start_date_of_period": "2023-10-16", "end_date_of_period": "2023-10-20", "period_end_close_price": 9200, "period_change": 100, "period_change_percentage": 1.1 }
        ]
        ```
-   **Logic / Algorithm:**
    1.  **Preparation:** The stock `code` is uppercased and `granularity` is lowercased.
    2.  **Date Handling:** The input `start_date` and `end_date` strings are parsed. If they are invalid or missing, sensible defaults are applied (e.g., a 5-day range). If `start_date` is after `end_date`, they are swapped.
    3.  **API Call:** A request is made to the backend historical data API for the processed date range.
    4.  **Data Processing:**
        -   If the API returns no data, a user-facing error message is returned.
        -   The raw API response is mapped to a standardized internal `DailyMarketDataItem` struct.
        -   The list of daily data is **sorted from newest to oldest**. This is critical for the next step.
    5.  **Aggregation (based on `granularity`):**
        -   If `daily`, the sorted list is returned as-is.
        -   If `weekly`, `monthly`, `quarterly`, or `yearly`, the daily data is grouped into periods (e.g., all days in week "2023-W43").
        -   The periods are sorted from newest to oldest.
        -   For each period, an aggregated summary is calculated:
            -   `period_end_close_price`: The close price of the newest day in the period.
            -   `period_change`: The difference between the close price of the newest day and the oldest day in the period.
            -   `period_change_percentage`: The percentage change calculated from the period's start and end prices.
    6.  The final list of daily or aggregated data is marshalled into a JSON string and returned.

---

## Tool: Financial Report Tools

This is a group of four related tools that retrieve specific financial statement data.

-   `financial_annualreport`
-   `financial_quarterreport`
-   `financial_ttmreport` (Trailing Twelve Months)
-   `financial_ytdreport` (Year to Date)

> **Description (Example for Annual):** Requests annual financial report data from a financial API.

-   **Purpose:** To fetch specific line items (e.g., "Revenue", "Net Income") from a company's financial statements, aggregated in different ways (annually, quarterly, etc.).
-   **Input Arguments:** All four tools use the same schema.
    ```json
    {
      "type": "object",
      "properties": {
        "code": {"type": "string", "description": "The 4-letter stock code, e.g., BBCA"},
        "start_date": {"type": "string", "description": "Start date, e.g., '2022' or '2023-01-01'"},
        "end_date": {"type": "string", "description": "End date, e.g., '2023' or '2023-12-31'"},
        "name": {
          "type": "string",
          "description": "Name of the financial metric",
          "enum": ["Revenue", "Net Income", "Total assets", "Total liabilities", "Cash from operating act", "Cash from financing act", "Cash from investing act"]
        }
      },
      "required": ["code", "name"]
    }
    ```
-   **Output Format:** A JSON object containing metadata and an array of financial values. The structure varies slightly based on the tool.
    -   **For `financial_quarterreport`:**
        ```json
        {
          "start_date": "2022 Q1",
          "end_date": "2023 Q2",
          "stock_code": "BBCA",
          "indicator": "quarter",
          "value": [
            { "period": "2023 Q2", "name": "Net Income", "value": 12000000000000, "type": "nominal" },
            { "period": "2023 Q1", "name": "Net Income", "value": 11500000000000, "type": "nominal" }
          ]
        }
        ```
    -   **For `financial_ttmreport`:**
        ```json
        {
          "YoYTTMStartValue": 40.5, "YoYTTMEndValue": 48.6,
          "YoYTTMStartPeriod": ["2022 Q1", "2022 Q2", "2022 Q3", "2022 Q4"],
          "YoYTTMEndPeriod": ["2023 Q1", "2023 Q2", "2023 Q3", "2023 Q4"],
          "YoYTTMGrowth": 20.0, "YoYTTMGrowthValue": 8.1,
          // ... QoQ fields ...
          "name": "net income", "stock_code": "BBCA", "indicator": "TTM"
        }
        ```
-   **Logic / Algorithm:**
    -   **`financial_annualreport` / `financial_quarterreport`:**
        1.  Calls the backend financial API to get all available data for the specified `code` and period type (`annual` or `quarter`). It fetches both `nominal` values and `percentage` growth values.
        2.  It applies default date ranges if none are provided (typically a 5-year span). It intelligently handles various date formats (e.g., "2023", "2023 Q2", "2023-06-30").
        3.  It filters the comprehensive list of data down to only the records that match the requested metric `name` and fall within the date range.
        4.  The final filtered list is packaged into a JSON object and returned.
    -   **`financial_ttmreport`:**
        1.  Fetches all available quarterly `nominal` data for the stock.
        2.  Determines the four quarters that constitute the TTM period for the `end_date`.
        3.  Determines the four quarters that constitute the TTM period for the `start_date`.
        4.  Sums the values for the metric `name` for each of these two TTM periods.
        5.  Calculates the Year-over-Year (YoY) and Quarter-over-Quarter (QoQ) growth between the two TTM sums.
        6.  Returns a detailed JSON object with the start and end TTM values, the periods used for the calculation, and the resulting growth figures.
    -   **`financial_ytdreport`:**
        1.  Fetches all available quarterly `nominal` data for the stock.
        2.  For each year within the specified date range, it identifies the relevant quarters to sum (from Q1 up to the quarter specified in the `end_date`).
        3.  It sums the values for the metric `name` across these quarters for each year.
        4.  Returns a JSON object containing a list of years, each with its calculated YTD cumulative value.

---

## Tool: Financial Ratio Tools

This is a group of four related tools that retrieve pre-calculated financial ratios.

-   `financial_profitability_ratio` (ROA, ROE, GPM, OPM, NPM)
-   `financial_solvency_ratio` (Current Ratio, Quick Ratio, Debt to Equity)
-   `financial_valuation_ratio` (PER, PSR, PBV, PCFR, EV/EBITDA)
-   `financial_dividend_ratio` (Dividend, Payout Ratio)

> **Description (Example for Profitability):** Retrieves Profitability financial ratios (ROA, ROE, GPM, OPM, NPM) for a given stock.

-   **Purpose:** To provide a convenient way to access common financial ratios without needing to fetch the underlying financial statement data and calculate them manually.
-   **Input Arguments:** All four tools use the same schema. `start_date` and `end_date` are optional.
    ```json
    {
      "type": "object",
      "properties": {
        "code": {"type": "string", "description": "The stock ticker symbol (e.g., 'BBCA')."},
        "start_date": {"type": "string", "description": "Optional start date ('YYYY-MM-DD' or 'YYYY QX')."},
        "end_date": {"type": "string", "description": "Optional end date ('YYYY-MM-DD' or 'YYYY QX')."}
      },
      "required": ["code"]
    }
    ```
-   **Output Format:** A JSON object where the key is the category of ratios requested (e.g., "Profitability"), containing an array of ratio values over time.
    ```json
    {
      "stock_code": "BBCA",
      "start_date": "2021 Q4",
      "end_date": "2023 Q3",
      "Profitability": [
        { "period": "2023 Q3", "name": "ROE TTM", "value": 21.5 },
        { "period": "2023 Q3", "name": "ROA TTM", "value": 3.8 },
        { "period": "2023 Q2", "name": "ROE TTM", "value": 21.2 }
      ]
    }
    ```
-   **Logic / Algorithm:**
    1.  All four tools use a shared helper function, `fetchAndPrepareFinancialData`.
    2.  This function first normalizes the date range, providing a 5-year default if none is specified.
    3.  It then makes a single API call to fetch **all available quarterly financial data** for the stock. This is an efficient optimization to avoid multiple API calls.
    4.  The main tool function (e.g., `FinancialProfitabilityRatio`) then calls another helper, `createRatioResult`, passing in the category name (e.g., "Profitability").
    5.  `createRatioResult` uses an internal map to identify which specific metrics belong to the requested category (e.g., "Profitability" -> `["ROA TTM", "ROE TTM", ...]`).
    6.  It filters the large dataset from step 3, keeping only the metrics that match the category and fall within the requested date range.
    7.  **Special Case for `financial_valuation_ratio`**: Before filtering, this specific tool makes an additional API call to get the company's Book Value Per Share (BVPS) and the stock's last price to calculate the *current* Price-to-Book Value (PBV). This live PBV value is added to the historical dataset as a synthetic point for the current quarter, providing the most up-to-date valuation metric.
    8.  The final filtered list is embedded in a JSON object under a key corresponding to its category and returned.

---

## Tool: `stock_valuation`

> Get company quality (e.g: excellent, good, bad), stock valuation (e.g: fair_value, overvalued, undervalued), and bullish signals.

-   **Purpose:** To provide a comprehensive, multi-faceted valuation summary of a stock by combining several different data points into a single, cohesive analysis.
-   **Input Arguments:**
    ```json
    {
      "type": "object",
      "properties": {
        "code": {
          "type": "string",
          "description": "The 4-letter stock code, for example: BBCA"
        }
      },
      "required": ["code"]
    }
    ```
-   **Output Format:** A single, detailed JSON object summarizing the valuation.
    ```json
    {
      "stock": "BBCA",
      "last_price": 9100,
      "last_price_time": "2023-10-27T11:45:00+07:00",
      "company_quality": "excellent",
      "bullish_fair_value": 9800,
      "bearish_fair_value": 8900,
      "median_fair_value": 9350,
      "valuation": "fair_valued",
      "bullish_signal_number": 3,
      "bullish_signals": ["Golden Cross", "MACD Crossover", "Uptrend"]
    }
    ```
-   **Logic / Algorithm:**
    1.  The tool initiates four separate API calls **in parallel** to maximize speed:
        -   Get the latest stock price.
        -   Get the company's quality rating (e.g., "excellent", "good").
        -   Get the analyst consensus fair value range (bearish and bullish price targets).
        -   Get the active technical trading signals (e.g., "Golden Cross").
    2.  It uses a `sync.WaitGroup` to wait for all four network requests to complete. Errors from any request are collected. If any fail, the entire tool fails.
    3.  Once all data is retrieved, it performs business logic:
        -   It calculates the `median_fair_value` from the bearish and bullish targets.
        -   It determines the `valuation` status by comparing the `last_price` to the fair value range (`undervalued`, `fair_valued`, or `overvalued`).
        -   If the stock is not fair-valued, it may append a percentage to the valuation string (e.g., `"undervalued 15.20%"`).
    4.  All the raw and calculated data points are assembled into the final `ValuationResult` struct.
    5.  The result is marshalled into a JSON string and returned.

---

## Tool: `analyze_stock`

> Always use this tool if user ask you to 'analyze' any stock. Get company related research data (business_line, competitive_advantage) to be used by LLM to analyze the stock quality.

-   **Purpose:** To retrieve a complete, qualitative research document about a company from an internal database. This provides deep, human-written analysis and context (such as business model, industry insights, and competitive landscape) that is not available in purely quantitative tools like financial reports or market data. The output is the **full, raw research report**, intended for the LLM to read and synthesize for its final analysis.

-   **Input Arguments:**
    ```json
    {
      "type": "object",
      "properties": {
        "code": {
          "type": "string",
          "description": "The 4-letter stock code, for example: BBCA"
        }
      },
      "required": ["code"]
    }
    ```

-   **Output Format:** A pretty-printed JSON object representing the entire `ResearchReportDoc` structure as stored in the database. If no document is found, it returns a plain text message.

    The primary field for the LLM is `report_content`, which contains the full text of the analysis.

    **Example Output (Content Truncated for Brevity):**
    ```json
    {
      "_key": "BMRI.docx_BMRI",
      "filename": "BMRI.docx",
      "stock_code": "BMRI",
      "report_content": "BMRI (PT Bank Mandiri (Persero) Tbk) is Indonesia's largest bank by assets, loans, and deposits... \n\n## Company profile\n\nBMRI’s revenue is predominantly driven by its Loan segment...\n\n## Bullish Valuation\n\nUpstream – Capital Sourcing\nBMRI primarily raises capital through customer deposits...\n\n## Business Line\n\nRisk management is the core of banking...\n\n## Competitive Advantage Analysis\n\nIndustry Valuation: Indonesia’s credit growth set to expand as economy grows...\n\n[... extensive report content continues ...] \n\n[TABLE DATA]\nCompany Score | Best\nTicker | BMRI\n...\n[/TABLE DATA]",
      "created_timestamp": "2025-07-25T14:38:00.451254+07:00",
      "last_updated_timestamp": "2025-07-25T14:39:13.035925+07:00"
    }
    ```

-   **Logic / Algorithm:**
    1.  The input stock `code` is converted to uppercase.
    2.  It queries an ArangoDB database by calling `arangoStore.GetResearchDocByStockCode` to find a single research document where the `stock_code` field matches the input.
    3.  The database access is protected by a circuit breaker. If the database is unavailable, the tool will fail fast with a user-facing error.
    4.  If the query returns no document (the result is `nil`), the tool returns the specific plain text string: `"No research data related to <CODE> was found."`.
    5.  If a document is successfully retrieved, the entire `ResearchReportDoc` struct is marshalled into an indented (pretty-printed) JSON string.
    6.  This complete JSON string, containing all metadata and the full `report_content`, is returned as the tool's output.

---

## Tool: `frequently_asked`

> This is the primary tool for answering all user questions that seek knowledge, definitions, explanations, or guidance... CRITICAL INSTRUCTION: If the user's question is not in formal English, you MUST first translate it into formal English... DO NOT use your own internal knowledge. ALWAYS call this tool.

-   **Purpose:** This is the agent's primary Retrieval-Augmented Generation (RAG) tool. It is used to answer any question about Tuntun's products, services, policies, or general financial concepts by querying an external knowledge base. It is designed to be the default tool for most informational queries. It supports both standard blocking and real-time streaming responses.
-   **Input Arguments:**
    ```json
    {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "The user's question about products or services."
        }
      },
      "required": ["query"]
    }
    ```
-   **Output Format:** A plain text string containing the answer from the RAG system.
    ```text
    To register on the Tuntun application, you first need to download the app from the App Store or Google Play Store. Once installed, open the app and tap on the 'Register' button. You will be prompted to enter your email address and create a password...
    ```
-   **Logic / Algorithm:**
    1.  The tool checks that the Tencent RAG service is properly configured.
    2.  It constructs a request payload including the user's `query`, a unique request ID, and various application keys.
    3.  It makes a `POST` request to the Tencent RAG API, with headers indicating it expects a Server-Sent Events (`text/event-stream`) response. The HTTP client for this tool has a longer timeout (60s) to accommodate potentially slow LLM responses.
    4.  It handles non-200 OK status codes from the API as fatal errors.
    5.  It reads the response body as a stream, processing it line-by-line.
    6.  It parses the SSE protocol, looking for `event: reply` and `data: {...}` lines. It ignores other event types like `token_stat`.
    7.  The JSON in the `data` field is parsed. The tool looks for payloads where `IsFromSelf` is `false` (meaning the message is from the AI, not an echo of the user's query).
    8.  **For Blocking Execution (`TencentFrequentlyAsked`):**
        -   It keeps track of the most recent complete `Content` string from the AI.
        -   If it receives a message with `IsFinal: true`, it immediately stops processing and returns the content of that message.
        -   If the stream ends without a final marker, it returns the last complete content string it received.
    9.  **For Streaming Execution (`StreamTencentFrequentlyAsked`):**
        -   It maintains a copy of the `previousContent`.
        -   When a new AI message arrives, it calculates the *delta* (the new text added since the last message) by comparing the new content with the `previousContent`.
        -   This small delta string is sent immediately down a channel to the client as a `StreamEventToken`.
        -   It updates `previousContent` to the new content.
        -   This process repeats for every incoming message, creating a real-time typing effect for the user.
        -   The stream processing stops when a final marker is received or the connection closes.
