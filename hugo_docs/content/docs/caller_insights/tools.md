---
title: "Tools Documentation"
date: 2025-09-10
lastmod: 2026-07-10
draft: false
---

This document provides a detailed reference for every tool available to the agent. For each tool it records the exact registered name, purpose, input-argument schema, output format, and internal logic, to aid understanding, debugging, and future development.

The tool registry is defined in `tools/toolcore/definitions.go`. Description strings live in `tools/toolcore/descriptions.go` and JSON parameter schemas in `tools/toolcore/schemas.go`. Backend-enabled tools are implemented under `tools/toolbe/` and non-backend tools under `tools/toolnonbe/`.

> **Note on `compare_stocks`:** `compare_stocks` is intentionally NOT a registered, executable tool. It is a reserved terminal synthesis-step marker handled by the pipeline executor via the injected `ComparisonSynthesizer` (`chatbot/processing/comparison`). It therefore has no entry in the registry and is not documented as a callable tool below.

> **Note on conditional registration:** `query_user_short_term_memory` is only registered when the `EnableUserShortTermMemory` master switch is enabled in application settings. All other tools listed here are always registered unless explicitly disabled via the `DisabledTools` configuration.

The complete set of registered tools, grouped by their registry builder function, is:

- **Sector / Concept:** `concept_sector_search_by_stock_code`, `concept_sector_search`
- **Stock Insights:** `company_overview`, `stock_analysis`, `stock_analysis_from_research`
- **External Sources:** `web_search`, `news_summary`
- **Market Prices:** `realtime_market`, `historical_marketdata`
- **General Utility:** `get_current_time`, `frequently_asked`
- **Rankings / Selection:** `stock_selection`, `stock_ranks`
- **Financial Reports:** `financial_annualreport`, `financial_quarterreport`, `financial_ttmreport`, `financial_ytdreport`
- **Financial Ratios:** `financial_profitability_ratio`, `financial_solvency_ratio`, `financial_valuation_ratio`, `financial_dividend_ratio`
- **Mutual Funds:** `mutual_fund_analysis`, `mutual_fund_selection`, `mutual_fund_selection_v2`
- **Market Flow:** `foreign_flow`, `broker_summary`, `dominant_broker_analysis`
- **User Data:** `query_user_portfolio`, `query_user_memory`, `query_user_watchlist`, `query_user_short_term_memory` (conditional)

---

## Tool: `get_current_time`

> Use this tool if user ask about the current time. It takes no arguments.

-   **Purpose:** To provide the agent with the current server time and date, including timezone offset. This grounds any time-sensitive query.
-   **Input Arguments:** None. The tool is invoked with an empty object (`noArgsSchema`).
    ```json
    { "type": "object", "properties": {} }
    ```
-   **Output Format:** A single string representing the current time in [RFC3339](https://www.rfc-editor.org/rfc/rfc3339) format.
    ```
    2023-10-27T10:30:00+07:00
    ```
-   **Logic / Algorithm:**
    1.  Calls `time.Now()` for the current system time.
    2.  Formats it as an RFC3339 string.
    3.  Returns the string. (The executor is defined inline in `definitions.go`; no separate backend call is made.)

---

## Tool: `frequently_asked`

> This is the primary tool for answering all user questions that seek knowledge, definitions, explanations, or guidance. CRITICAL INSTRUCTION: If the user's question is not in formal English, you MUST first translate it into formal English and pass that translation as the `query` parameter. DO NOT use your own internal knowledge. ALWAYS call this tool. Do NOT use this tool for stock-specific research (use `stock_analysis_from_research`), stock valuation/bullish signals (use `stock_analysis`), or stock news (use `news_summary`).

-   **Purpose:** The agent's primary Retrieval-Augmented Generation (RAG) tool. It answers questions about Tuntun's products, services, policies, and general financial concepts by querying the Tencent RAG knowledge base. It supports both standard blocking and real-time streaming execution.
-   **Input Arguments:** Uses `queryArgsSchema`.
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
-   **Output Format:** For blocking execution, a JSON object marshalled from `FrequentlyAskedResult` containing the RAG answer and optional external-API logs.
    ```json
    {
      "content": "To register on the Tuntun application, download the app from the App Store or Google Play Store, open it, tap 'Register', and enter your email address and create a password...",
      "external_apis": []
    }
    ```
    If JSON marshalling fails, the raw `content` string is returned as a fallback.
-   **Logic / Algorithm:**
    1.  Verifies that `TencentRAGURL` and `TencentRAGBotAppKey` are configured.
    2.  Builds a `TencentRAGRequest` payload with the `query` as `content`, a request ID, and the configured bot/visitor/session keys.
    3.  Issues a `POST` request to the Tencent RAG API with `Accept: text/event-stream`. A dedicated HTTP client with a 60-second timeout accommodates slow LLM responses.
    4.  Treats non-200 status codes as fatal errors.
    5.  Reads the response as a Server-Sent Events stream, parsing `event`/`data` lines and ignoring payloads where `IsFromSelf` is true (echoes of the user query).
    6.  **Blocking (`TencentFrequentlyAsked`):** tracks the latest AI `Content`; on `IsFinal: true` it stops and returns that content, otherwise it returns the last content received before stream end.
    7.  **Streaming (`StreamTencentFrequentlyAsked`):** maintains `previousContent`, computes the delta of each new AI message, and emits the delta as a `StreamEventToken` down the stream channel, producing a real-time typing effect.
    8.  In blocking mode, if `RemoveMarkdownFormattingFromRAG` is enabled and content is non-empty, the tool invokes `ReformatMarkdownToSimpleText` (an LLM call) to strip markdown; on failure it keeps the original content.

---

## Tool: `news_summary`

> Use this tool to get the latest news articles for a given stock. The input should be the 4-letter stock code, for example: "BBCA".

-   **Purpose:** To retrieve recent news headlines and LLM-generated summaries for a specific publicly traded company.
-   **Input Arguments:** Uses `codeArgsSchema`.
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
-   **Output Format:** A JSON object marshalled from `NewsSummaryResult`. It contains a pre-formatted text block (`formatted_output`) with inline `[item_N]` markers, an `items` array of per-article metadata for multi-source citation, and optional `external_apis` logs.
    ```json
    {
      "formatted_output": "[item_1] Title: Bank Central Asia Reports Strong Q3 Earnings\n[item_1] Published Date: 2023-10-26T09:00:00+07:00\n[item_1] Summary: BBCA announced a 15% year-over-year increase in net profit...",
      "items": [
        {
          "title": "Bank Central Asia Reports Strong Q3 Earnings",
          "published_date": "2023-10-26T09:00:00+07:00",
          "summary": "BBCA announced a 15% year-over-year increase in net profit...",
          "link": "https://...",
          "source": "..."
        }
      ],
      "external_apis": []
    }
    ```
    When no news is found (or on a downstream error), the same structure is returned with an empty `items` array and a `formatted_output` such as `"No news found for BBCA."`.
-   **Logic / Algorithm:**
    1.  Upcases the `code` and verifies that `BeNewsLatestURL` is configured.
    2.  Constructs a `NewsRequestPayload` (`{"secCodes": ["<CODE>"]}`) and issues a `POST` request (timeouts handled centrally).
    3.  Distinguishes context cancellation from general network failures.
    4.  On non-200 status, malformed JSON, or a non-`"Success"` API message, returns a structured error result (preserving API logs for debugging).
    5.  If the returned list is empty, returns a "No news found" result (not an error).
    6.  Otherwise iterates the returned news items, preserving the **full** published timestamp, and builds both the `items` metadata array and the formatted text block.

---

## Tool: `web_search`

> Use this tool to search the internet for real-time information (current events, latest news, recent announcements, fact-checking, and the latest information about companies, products, or events).

-   **Purpose:** To perform a live web search using Gemini with the Google Search tool, returning structured, fact-checked results with per-item source attribution and single-language titles.
-   **Input Arguments:** Uses `webSearchSchema`.
    ```json
    {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "The search query string for web search."
        },
        "lang": {
          "type": "string",
          "description": "Language for title generation (en/id/zh). Defaults to 'en'.",
          "enum": ["en", "id", "zh"]
        }
      },
      "required": ["query"]
    }
    ```
-   **Output Format:** A JSON object with an `items` array (`WebSearchResult`), one entry per search result.
    ```json
    {
      "items": [
        {
          "fact": "BBRI reported ...",
          "title": "Bank Rakyat Indonesia Q3 Results",
          "url": "https://...",
          "date": "2023-10-26"
        }
      ]
    }
    ```
    If the Gemini output cannot be parsed as JSON, the extracted raw text is returned instead.
-   **Logic / Algorithm:**
    1.  Validates a non-empty `query` and defaults `lang` to `en`; verifies the Gemini API key is configured.
    2.  Enhances the query by resolving stock codes to company names (e.g. `BBRI` → `BBRI (Bank Rakyat Indonesia (Persero) Tbk)`); resolution failures fall back to the original query.
    3.  Builds a `GenerateContentConfig` with temperature 0.1, JSON response MIME type, a language-specific fact-checker system prompt, and the Google Search tool.
    4.  Calls Gemini `GenerateContent`. On failure it emits a deduplicated DingTalk alert (skipping context cancellation) and best-effort records the exact prompt-token count via the remote `CountTokens` endpoint.
    5.  Parses the response into a `ResponseWrapper` (accepting either a wrapper object or a bare array), then resolves each grounding redirect URL to its final destination in parallel.
    6.  Records Gemini token-usage metrics and returns the marshalled result.

---

## Tool: `realtime_market`

> Gets the CURRENT, LIVE market data for stocks with comprehensive market insights (basic price data, orderbook depth, tradebook analysis, and market microstructure). Use this ONLY for the price 'right now' or the 'latest' single price point. DO NOT use this for trends, history, or any period of time.

-   **Purpose:** To fetch a real-time snapshot for one or more stocks, including latest price, change, volume, and other daily metrics, alongside orderbook and tradebook microstructure data.
-   **Input Arguments:** Uses `codesListSchema`.
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
-   **Output Format:** A series of JSON objects, one per requested stock, separated by newlines. If a specific stock cannot be found, an error object is emitted for that code.
    ```json
    {"code":"BBCA","date":"2023-10-27","time":"11:15","last price":9100,"change":-25,"change%":"-0.27%","previous close price":9125,"open price":9125,"high price":9150,"low price":9075,"value":"1.2 T","volume":"131.9 M","Average Price":9105.5,"Frequency":"15,789"}
    {"code": "INVALID", "error": "No data found"}
    ```
-   **Logic / Algorithm:**
    1.  Validates that the `codes` list is non-empty and upcases every code.
    2.  Issues a single `POST` request to the backend price-summary API with the list of codes.
    3.  Places the returned per-stock data into a map keyed by code for efficient lookup.
    4.  Iterates the **original** requested list; for each code it either formats the raw data into a `FormattedMarketData` object (humanizing large values such as `value` and `volume` into strings like "1.2 T") or emits a per-code error object.
    5.  Appends each resulting JSON object to the output, newline-separated.

---

## Tool: `historical_marketdata`

> Gets HISTORICAL data for a stock's performance OVER A PERIOD OF TIME. This is ESSENTIAL for analyzing trends, charts, and price movements between a start and end date. Use this for ANY query that involves a date range like 'last week', 'past year', 'daily movement', 'since January', etc.

-   **Purpose:** To retrieve historical end-of-day trading data over a specified period and aggregate it by a chosen time granularity.
-   **Input Arguments:** Uses `historicalMarketSchema`.
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
-   **Output Format:** A JSON array whose object structure depends on `granularity`.
    -   **`granularity: "daily"`:**
        ```json
        [
          { "date": "2023-10-26", "close price": 9125, "change": -25, "change%": -0.27, "volume": 150000000 }
        ]
        ```
    -   **Aggregated granularities (e.g. `"weekly"`):**
        ```json
        [
          { "period_identifier": "2023-W43", "start_date_of_period": "2023-10-23", "end_date_of_period": "2023-10-26", "period_end_close_price": 9125, "period_change": -75, "period_change_percentage": -0.82 }
        ]
        ```
-   **Logic / Algorithm:**
    1.  Upcases `code` and lowercases `granularity`.
    2.  Parses `start_date`/`end_date`, applying sensible defaults when invalid or missing and swapping them if reversed.
    3.  Calls the backend historical-data API for the processed range.
    4.  Maps the raw response into a standardized `DailyMarketDataItem` list, sorted newest-to-oldest.
    5.  For `daily`, returns the sorted list as-is; otherwise groups days into periods (sorted newest-to-oldest) and computes per-period `period_end_close_price`, `period_change`, and `period_change_percentage`.
    6.  Marshals the final list to a JSON string.

---

## Tool: `stock_analysis`

> Call this tool if the user asks you to analyze one or more stocks, or for an official Tuntun Buy/Hold/Sell recommendation. Returns company quality, fair-value valuation, and trading signals for each stock.

-   **Purpose:** To provide comprehensive quantitative analysis for one or more stocks by combining company quality, fair-value valuation, and bullish trading signals into a single structured result. (This tool supersedes the former `stock_valuation` tool.)
-   **Input Arguments:** Uses `codesListSchema`.
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
-   **Output Format:** A JSON object (`multisource.Result`) containing a pre-formatted text block (`formatted_output`) and an `items` array with one entry per stock. Each item carries `stock`, `last_price`, `last_price_time`, `company_quality`, `stock_valuation`, `bullish_signals`, and `is_data_available`. When data is unavailable for a stock, only `stock` and `is_data_available: false` are emitted for that item.
    ```json
    {
      "formatted_output": "Stock: BBCA\nLast Price: 9100\nCompany Quality: BEST\nValuation: fair_valued\n...",
      "items": [
        {
          "stock": "BBCA",
          "last_price": 9100,
          "last_price_time": "2023-10-27T11:45:00+07:00",
          "company_quality": { "company_quality": "BEST" },
          "stock_valuation": { "last_price": 9100, "bearish_fair_value": 8900, "bullish_fair_value": 9800, "valuation": "fair_valued" },
          "bullish_signals": [ { "name": "Golden Cross" } ],
          "is_data_available": true
        }
      ]
    }
    ```
-   **Logic / Algorithm:**
    1.  Requires a non-null `DataStore` (used for LCMP translations) and a non-empty `codes` list.
    2.  Analyzes every stock **in parallel**; any hard failure aborts the whole tool.
    3.  For each stock, `analyzeSingleStock` first fetches the last price, then issues four parallel calls: Fair Value v2, Company Quality v2, Trading Info, and the iStock Tuntun guidance summary. iStock failures degrade gracefully (they do not fail the analysis).
    4.  Company quality is resolved with LCMP-translation priority (falling back to the raw quality string).
    5.  Valuation status is derived by comparing the last price to the bearish/bullish fair-value range, yielding `undervalued`, `fair_valued`, or `overvalued`, with an appended percentage (relative to the median) when not fair-valued.
    6.  Bullish signals from the two-day and five-day signal lists are LCMP-translated.
    7.  Marks `is_data_available` false when the last price is not positive, and marshals a multi-source result for citation expansion downstream.

---

## Tool: `stock_analysis_from_research`

> Call this tool if the user asks you to analyze any stock, or asks about the research report of a certain stock. Returns company research data (business line, competitive advantage) for the LLM to synthesize. Supports an optional `summarize` flag.

-   **Purpose:** To retrieve a qualitative, human-written research document about a company from the ArangoDB research store. This provides deep narrative context (business model, industry insights, competitive landscape) not present in quantitative tools. (This tool replaces the former `analyze_stock` tool.)
-   **Input Arguments:** Uses `financialResearchSchema`.
    ```json
    {
      "type": "object",
      "properties": {
        "code": {
          "type": "string",
          "description": "The 4-letter stock code, for example: BBCA"
        },
        "summarize": {
          "type": "boolean",
          "description": "When true, returns a concise summary (70-80% reduction). When false or omitted, returns full research document.",
          "default": false
        }
      },
      "required": ["code"]
    }
    ```
-   **Output Format:** A unified JSON envelope with a top-level `last_updated` and a `research` object. The research object always includes `is_research_document_found`; the internal `_key`, `filename`, and duplicate `last_updated_timestamp` fields are stripped. When `summarize` is false, `research.report_content` holds the full text; when summarization succeeds, `report_content` is omitted and `research.summary` is populated instead. If no document exists, a plain-text message is returned.
    ```json
    {
      "last_updated": "2025-07-25T14:39:13.035925+07:00",
      "research": {
        "stock_code": "BMRI",
        "report_content": "BMRI (PT Bank Mandiri (Persero) Tbk) is Indonesia's largest bank...",
        "created_timestamp": "2025-07-25T14:38:00.451254+07:00",
        "is_research_document_found": true
      }
    }
    ```
    No-document case: `"No research data related to BMRI was found."`
-   **Logic / Algorithm:**
    1.  Upcases `code` and calls `arangoStore.GetResearchDocByStockCode`.
    2.  Handles the ArangoDB circuit-breaker open state, context cancellation, and generic DB errors distinctly.
    3.  If the document pointer is nil, returns the plain-text "No research data" message.
    4.  When `summarize` is true and an LLM/tokenizer are available: uses a cached `Summary` when present; otherwise generates a new summary via LLM (targeting a 70-80% reduction) and caches it back to the database. On success, `ReportContent` is cleared and `Summary` set.
    5.  Marshals the (possibly modified) document to indented JSON and wraps it with the `last_updated` envelope and `is_research_document_found` flag.

---

## Tool: `company_overview`

> Provides comprehensive company overview data for a stock: company profile, shareholders, board members, insider transactions, shareholder composition, and corporate actions, fetched in parallel.

-   **Purpose:** To assemble a broad company profile combining company information, shareholder structure, board of directors and commissioners, historical shareholder counts, insider transactions, ownership composition, and corporate-action history.
-   **Input Arguments:** Uses `codeArgsSchema`.
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
-   **Output Format:** An indented JSON object aggregating the fetched sections (Company Overview, Shareholder, Board of Directors and Commissioners, ShareholderCounts, Insider, Shareholder Composition, Corporate Action). On a missing code or unavailable `DataStore`, an `{"error": "..."}` object is returned.
-   **Logic / Algorithm:**
    1.  Validates a non-empty `code` and a non-null `DataStore`.
    2.  Upcases the code.
    3.  Delegates to `toolutils.ProcessCompanyOverview`, which fetches the constituent datasets in parallel; network/system errors are propagated.
    4.  Marshals the aggregated result to indented JSON.

---

## Tool: `concept_sector_search_by_stock_code`

> Searches for investment concepts and sectors that contain a specific stock code, using the loaded concept-sector JSON data directly (reverse lookup, no Elasticsearch dependency).

-   **Purpose:** To find which investment concepts/sectors include a given stock, returning concept explanations, latest market data, and constituent-stock lists.
-   **Input Arguments:** Uses `codeArgsSchema`.
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
-   **Output Format:** A JSON result describing the concept sectors containing the stock, each with its name, explanation, latest market metrics (price changes, volume), the list of constituent stocks, and market-performance counts (gainers, losers, neutrals). On empty input or an unavailable `DataStore`, an `{"error": "..."}` object is returned.
-   **Logic / Algorithm:**
    1.  Validates a non-empty stock code and a non-null `DataStore`.
    2.  Constructs a `ConceptSectorTool` with the LLM, tokenizer, and DataStore.
    3.  Runs `SearchByStockCodeUsingJSON`, scanning the in-memory concept-sector JSON for concepts whose constituent lists contain the code.
    4.  Formats matching concepts (with market data and constituents) into the returned result.

---

## Tool: `concept_sector_search`

> Searches for investment concepts and sectors using LLM-based semantic matching over the full concept-sector dataset (instead of keyword/Elasticsearch search).

-   **Purpose:** To find investment themes, industry sectors, and market concepts relevant to a natural-language query, leveraging the LLM for nuanced semantic understanding.
-   **Input Arguments:** Uses `conceptSectorSchema`.
    ```json
    {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "The search query for concepts or sectors. For example: 'renewable energy', 'banking sector', 'technology companies'"
        },
        "language": {
          "type": "string",
          "description": "The language for search and results. Supported: 'en' (English), 'zh' (Chinese), 'id' (Indonesian). Defaults to 'en'.",
          "enum": ["en", "zh", "id"]
        },
        "topn": {
          "type": "string",
          "description": "Maximum number of relevant sectors to return. Use '2' for pipeline mode, 'all' for default behavior. Examples: '1', '2', '3', 'all'. Defaults to 'all'."
        }
      },
      "required": ["query"]
    }
    ```
    The argument struct (`ConceptSectorSearchArgs`) maps `topn` to the `TopN` field.
-   **Output Format:** A JSON result listing the most relevant concept sectors selected by the LLM, each with concept name and explanation, latest market data, constituent stocks, and market-performance metrics.
-   **Logic / Algorithm:**
    1.  Passes `query`, `language`, and `topn` to `ConceptSectorSearchUsingLLM`.
    2.  The LLM analyzes the full concept-sector dataset and selects the most relevant concepts for the query (bounded by `topn`).
    3.  The selected concepts are enriched with market data and constituent lists and returned.

---

## Tool: `stock_selection`

> Get curated Tuntun stock selections for investing and/or trading strategies. Accepts an optional `type` to filter results.

-   **Purpose:** To return curated stock recommendations: long-term **investing** selections (fundamental analysis, company quality, fair value) and short-term **trading** selections (technical analysis, bullish signals, Fibonacci levels).
-   **Input Arguments:** Uses `stockSelectionSchema`.
    ```json
    {
      "type": "object",
      "properties": {
        "type": {
          "type": "string",
          "description": "Selection type to filter results. 'investing', 'trading', or 'all' (default).",
          "enum": ["investing", "trading", "all"]
        }
      }
    }
    ```
    `type` is optional; there are no required fields.
-   **Output Format:** A JSON object with `is_data_available`, a pre-formatted `formatted_output` text block, and an `items` array of selection sections. Each section carries `selection_type` ("Investing Selection" / "Trading Selection"), the parsed `stocks`, `stock_count`, and `today_date`.
    ```json
    {
      "is_data_available": true,
      "formatted_output": "Stock Selection Results\n\nInvesting Selection: 5 stocks\nStock: BBCA (Bank Central Asia) - Price: 9100 - Quality: BEST - Action: Buy\n...",
      "items": [
        { "selection_type": "Investing Selection", "stocks": [ ... ], "stock_count": 5, "today_date": "2023-10-27" }
      ]
    }
    ```
    If all requested APIs fail, an `is_data_available: false` object with an `error_message` and empty `items` is returned.
-   **Logic / Algorithm:**
    1.  Validates/defaults `type` to `all`.
    2.  Determines which APIs to call (investing, trading, or both) and launches them in parallel goroutines with panic recovery.
    3.  Collects results with context-cancellation support; when all requested APIs fail, returns the all-failed structured response; partial failures degrade gracefully.
    4.  Parses each API's raw stock list into typed items (`StockSelectionInvestingItem` / `StockSelectionTradingItem`), skipping malformed entries and clearing internal fields (logos, LCMP codes, URLs).
    5.  Builds the formatted output and `items` array, then marshals the `StockSelectionExpandedResult`.

---

## Tool: `stock_ranks`

> Get comprehensive stock rankings across market performance, fundamental analysis, technical analysis, and market-intelligence categories.

-   **Purpose:** To fetch ranked stock lists for one or more categories (gainers/losers/active/value/volume, growth/profitability/undervalued, technical signals, bandar tracker, event-driven, bullish signals).
-   **Input Arguments:** Uses `stockRanksSchema`.
    ```json
    {
      "type": "object",
      "properties": {
        "ranks": {
          "type": "string",
          "description": "Comma-separated ranking categories. Available: Top Gainer, Top Loser, Top Active, Top Value, Top Volume, Top Growth, Top Profitability, Top Undervalued, Technical Analysis, Bandar Tracker, Event Driven, Top Bullish Signals"
        },
        "period": {
          "type": "string",
          "description": "Time period for ranking data (e.g., '1d', '5d', '20d', '60d', '52w'). Defaults to '1d'"
        }
      }
    }
    ```
    Both fields are optional; defaults are applied when omitted.
-   **Output Format:** An indented JSON object (`StockRanksMultiSourceResult`) with a `formatted_output` text block, an `items` array (one entry per rank category with `rank_type`, `stocks`, `stock_count`, `latest_timestamp`, `period`, and `is_data_available`), and optional `external_apis` logs.
    ```json
    {
      "formatted_output": "Rank Type: Top Gainer\nLatest Timestamp: ...\nPeriod: 1d\nStocks: 10\nStock 1: BBCA - Bank Central Asia - Price: 9100 - Change: 50 (0.55%)\n...",
      "items": [
        { "rank_type": "Top Gainer", "stocks": [ ... ], "stock_count": 10, "latest_timestamp": "...", "period": "1d", "is_data_available": true }
      ]
    }
    ```
-   **Logic / Algorithm:**
    1.  Requires a non-null `DataStore`; defaults `ranks` and `period` when empty.
    2.  Splits `ranks` into a trimmed list and calls `toolutils.GetStockRanks`.
    3.  On partial or total upstream failure, degrades gracefully: emits `is_data_available: false` items for each failed rank (with a "DATA CURRENTLY UNAVAILABLE" cue) so the LLM can report unavailability rather than aborting.
    4.  Normalizes heterogeneous per-category response shapes (typed slices, tag-grouped maps, and generic map lists) into `StockRankData` items.
    5.  Builds the formatted output (with category-specific fields such as growth, ROE, undervaluation, fair-value range, valuation, and signals) and marshals the multi-source result.

---

## Tool: Financial Report Tools

A group of four related tools retrieving specific financial-statement line items:

-   `financial_annualreport` — "Requests annual financial report data from a financial API."
-   `financial_quarterreport` — "Requests quarter financial report data from a financial API."
-   `financial_ttmreport` — "Requests quarter financial report data ... and process it into TTM Format." (Trailing Twelve Months)
-   `financial_ytdreport` — "Requests yearly financial report data ... and process it into yearly Format." (Year to Date)

-   **Purpose:** To fetch selected financial metrics (e.g. Revenue, Net Income) from a company's statements, aggregated annually, quarterly, on a trailing-twelve-months basis, or year-to-date.
-   **Input Arguments:** All four share `financialReportSchema`. Note that the metric parameter is `names` (an **array**), not a single `name`; only `code` is required, and an empty/omitted `names` returns all seven metrics.
    ```json
    {
      "type": "object",
      "properties": {
        "code": {"type": "string", "description": "The 4-letter stock code, e.g., BBCA"},
        "start_date": {"type": "string", "description": "Start date, e.g., '2022' or '2023-01-01'"},
        "end_date": {"type": "string", "description": "End date, e.g., '2023' or '2023-12-31'"},
        "names": {
          "type": "array",
          "items": {
            "type": "string",
            "enum": ["Revenue", "Net Income", "Total assets", "Total liabilities", "Cash from operating act", "Cash from financing act", "Cash from investing act"]
          },
          "description": "List of financial metrics to retrieve. If empty or omitted, returns all 7 metrics.",
          "default": []
        }
      },
      "required": ["code"]
    }
    ```
    The `FinancialReportArgs.GetMetrics()` helper returns `AllFinancialMetrics` (all seven) when `names` is empty.
-   **Output Format:** A JSON object with request metadata plus the requested values. Shape varies by tool.
    -   **`financial_annualreport` / `financial_quarterreport`:**
        ```json
        {
          "start_date": "2022 Q1",
          "end_date": "2023 Q2",
          "stock_code": "BBCA",
          "indicator": "quarter",
          "value": [
            { "period": "2023 Q2", "name": "Net Income", "value": 12000000000000, "type": "nominal" }
          ]
        }
        ```
    -   **`financial_ttmreport`:**
        ```json
        {
          "YoYTTMStartValue": 40.5, "YoYTTMEndValue": 48.6,
          "YoYTTMStartPeriod": ["2022 Q1", "2022 Q2", "2022 Q3", "2022 Q4"],
          "YoYTTMEndPeriod": ["2023 Q1", "2023 Q2", "2023 Q3", "2023 Q4"],
          "YoYTTMGrowth": 20.0, "YoYTTMGrowthValue": 8.1,
          "name": "net income", "stock_code": "BBCA", "indicator": "TTM"
        }
        ```
    -   **`financial_ytdreport`:** a JSON object with a list of years, each carrying its cumulative YTD value for the requested metric(s).
-   **Logic / Algorithm:**
    -   **`financial_annualreport` / `financial_quarterreport`:**
        1.  Calls the backend financial API for all available data of the given `code` and period type (`annual` or `quarter`), fetching both nominal and percentage-growth values.
        2.  Applies default date ranges when none are provided (typically a 5-year span), handling formats such as "2023", "2023 Q2", and "2023-06-30".
        3.  Filters to records matching each requested metric in `names` (all seven when unspecified) within the date range.
        4.  Packages the filtered list into the response object.
    -   **`financial_ttmreport`:**
        1.  Fetches all available quarterly nominal data.
        2.  Determines the four quarters composing the TTM window for both `end_date` and `start_date`.
        3.  Sums each metric over both windows and computes Year-over-Year and Quarter-over-Quarter growth.
        4.  Returns start/end TTM values, the periods used, and growth figures.
    -   **`financial_ytdreport`:**
        1.  Fetches all available quarterly nominal data.
        2.  For each year in range, sums the quarters from Q1 through the quarter implied by `end_date`.
        3.  Returns the per-year cumulative YTD values.

---

## Tool: Financial Ratio Tools

A group of four related tools retrieving pre-calculated financial ratios:

-   `financial_profitability_ratio` — Profitability ratios (ROA, ROE, GPM, OPM, NPM)
-   `financial_solvency_ratio` — Solvency ratios (Current Ratio, Quick Ratio, Debt to Equity)
-   `financial_valuation_ratio` — Valuation ratios (PER, PSR, PBV, PCFR, EV/EBITDA)
-   `financial_dividend_ratio` — Dividend ratios (Dividend, Payout Ratio)

-   **Purpose:** To provide convenient access to common financial ratios without fetching and computing from raw statements.
-   **Input Arguments:** All four share `financialRatioSchema`. Only `code` is required; `start_date` and `end_date` are optional.
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
-   **Output Format:** A JSON object keyed by the ratio category (e.g. "Profitability"), containing an array of time-series ratio values.
    ```json
    {
      "stock_code": "BBCA",
      "start_date": "2021 Q4",
      "end_date": "2023 Q3",
      "Profitability": [
        { "period": "2023 Q3", "name": "ROE TTM", "value": 21.5 },
        { "period": "2023 Q3", "name": "ROA TTM", "value": 3.8 }
      ]
    }
    ```
-   **Logic / Algorithm:**
    1.  A shared helper (`fetchAndPrepareFinancialData`) normalizes the date range (defaulting to a 5-year span) and makes a single API call to fetch **all** available quarterly financial data for the stock.
    2.  Each tool (e.g. `FinancialProfitabilityRatio`) invokes `createRatioResult` with its category name.
    3.  `createRatioResult` uses an internal category-to-metrics map to select the relevant metrics and filters the dataset to those metrics within the requested range.
    4.  **Special case for `financial_valuation_ratio`:** before filtering, it makes an additional call to obtain the Book Value Per Share (BVPS) and last price to compute the *current* Price-to-Book Value (PBV), injecting it as a synthetic current-quarter point.
    5.  The filtered list is embedded under the category key and returned.

---

## Tool: `mutual_fund_analysis`

> Analyzes mutual funds by searching for them by name and retrieving detailed information (fund info, asset allocation, investment-manager details, risk profile, and historical performance).

-   **Purpose:** To resolve a mutual fund from a natural-language query and return its comprehensive profile.
-   **Input Arguments:** Uses `queryArgsSchema`.
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
-   **Output Format:** A JSON `MutualFundAnalysisResult` with an `is_data_available` flag and, when found, the fund's structured details (name, type, performance metrics, asset-allocation percentages, investment-manager company and fees, and risk profile).
-   **Logic / Algorithm:**
    1.  `SearchMutualFundUsingLLM` uses the LLM to identify the most relevant fund matching the query.
    2.  The selected fund's detailed data is fetched and structured into the result.
    3.  `is_data_available` reflects whether a fund was matched (driving single-source citation exclusion when false).

---

## Tool: `mutual_fund_selection`

> Get mutual fund investment recommendations and overall market valuation. Takes no arguments.

-   **Purpose:** To return investment guidance for mutual funds, including the current market valuation status and recommended index-fund and stable-fund picks.
-   **Input Arguments:** None (`noArgsSchema`).
    ```json
    { "type": "object", "properties": {} }
    ```
-   **Output Format:** An indented JSON object covering general market information (market valuation status such as VERY CHEAP / CHEAP / FAIR / EXPENSIVE / VERY EXPENSIVE, and an invest recommendation), index-fund recommendations (name, type, potential profit, current valuation), and stable-fund recommendations (name, type, 1-year and 3-year profit).
-   **Logic / Algorithm:**
    1.  Calls `toolutils.ProcessMutualFundSelection`; network/system errors are propagated.
    2.  Marshals the returned recommendation object to indented JSON.

---

## Tool: `mutual_fund_selection_v2`

> Get comprehensive mutual fund selection across three categories — stable, index, and stock funds. Accepts an optional `type` filter.

-   **Purpose:** To return detailed mutual-fund recommendations across stable funds (with risk analysis), index funds (with buy-point analysis), and stock funds (with equity-fund analysis).
-   **Input Arguments:** Uses `mutualFundSelectionSchema`.
    ```json
    {
      "type": "object",
      "properties": {
        "type": {
          "type": "string",
          "description": "Selection type to filter results. 'stable', 'index', 'stock', or 'all' (default).",
          "enum": ["stable", "index", "stock", "all"]
        }
      }
    }
    ```
    `type` is optional (mapped to `MutualFundSelectionV2Args.Type`); no required fields.
-   **Output Format:** A JSON object containing up to three sections — Stable Selection (name/type, 1-year return, return conclusion, risk level and reason, criteria), Index Selection (index name, conclusion and ROE, buy-point assessment and reason, available funds with expense ratios, criteria), and Stock Selection (name/type, equity-fund conclusion and reason, buy-point conclusion and reason, growth-since-inception vs IHSG, criteria).
-   **Logic / Algorithm:**
    1.  Passes the optional `type` to `toolbe.MutualFundSelectionV2` (backed by the `DataStore`).
    2.  Fetches and structures the requested selection categories (or all three when `type` is `all`/omitted).

---

## Tool: `foreign_flow`

> Get foreign flow data for Indonesian stocks showing buying/selling patterns by foreign and domestic investors.

-   **Purpose:** To provide net foreign flow, foreign and domestic buy/sell values and volumes, across market types and either predefined periods or explicit dates.
-   **Input Arguments:** Uses `foreignFlowSchema`. Only `code` is required.
    ```json
    {
      "type": "object",
      "properties": {
        "code": {"type": "string", "description": "The 4-letter stock code, e.g., BBCA"},
        "market": {"type": "string", "description": "Market type. Defaults to 'all'", "enum": ["all", "regular", "nego", "cash"]},
        "period": {"type": "string", "description": "Time period. Defaults to '1d'. Takes precedence over start_date/end_date when provided.", "enum": ["1d", "10d", "1w", "1M", "3M", "6M", "ytd"]},
        "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD). Used only when period is not provided."},
        "end_date": {"type": "string", "description": "End date (YYYY-MM-DD). Used only when period is not provided."}
      },
      "required": ["code"]
    }
    ```
-   **Output Format:** An indented JSON `ForeignFlowResult` with the net foreign flow summary, foreign/domestic buy-and-sell breakdowns, and an `is_data_available` flag. A missing code yields a structured result with `is_data_available: false` and an `error_message`.
-   **Logic / Algorithm:**
    1.  Validates `code` and `DataStore`; defaults `market` to `all`.
    2.  Applies the precedence rules: a non-standard `period` (e.g. "5d") is converted to explicit dates; a standard `period` takes precedence over dates; when neither is given, defaults to `period=1d`.
    3.  Upcases the code, validates the market type (defaulting to `all` on invalid input), and calls `toolutils.GetForeignFlow`.
    4.  Marshals the result to indented JSON.

---

## Tool: `broker_summary`

> Get broker summary data for Indonesian stocks: top buyers/sellers and accumulation/distribution analysis.

-   **Purpose:** To return the top 10 buyers and sellers (broker name, lots, values, average prices) and, when enabled, an accumulation/distribution sentiment analysis for a stock.
-   **Input Arguments:** Uses `brokerSummarySchema`. Only `code` is required.
    ```json
    {
      "type": "object",
      "properties": {
        "code": {"type": "string", "description": "The 4-letter stock code, e.g., BBCA"},
        "market_type": {"type": "string", "description": "Defaults to 'regular'", "enum": ["all", "regular", "nego", "cash"]},
        "investor_type": {"type": "string", "description": "Defaults to 'all'", "enum": ["all", "foreign", "domestic"]},
        "is_net": {"type": "string", "description": "Enable accumulation/distribution calculation. Defaults to '1'", "enum": ["1", "0"]},
        "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)."},
        "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)."}
      },
      "required": ["code"]
    }
    ```
-   **Output Format:** An indented JSON object with the top-buyers and top-sellers lists and, when `is_net=1`, an accumulation/distribution conclusion (Neutral, Small/Normal/Big Accumulation, or Small/Normal/Big Distribution). A missing code yields an `{"error": "..."}` object.
-   **Logic / Algorithm:**
    1.  Parses arguments; validates a non-empty `code`; upcases it.
    2.  Defaults `market_type` to `regular`, `investor_type` to `all`, and `is_net` to `1`.
    3.  Supports backward compatibility: a legacy `period` in the raw input is converted to start/end dates.
    4.  Applies default trading-day dates when unspecified, then calls the backend broker-summary API and marshals the result.

---

## Tool: `dominant_broker_analysis`

> Get dominant broker analysis showing the most active buyers and sellers for a stock across multiple time periods (1W, 1M, 3M, 6M).

-   **Purpose:** To identify the dominant buyer and seller brokerages per period, with transaction metrics, estimated P&L, dominance percentages, and a negotiate-market trade summary.
-   **Input Arguments:** Uses `dominantBrokerAnalysisSchema`. Note the property is `secCode` (not `code`).
    ```json
    {
      "type": "object",
      "properties": {
        "secCode": {
          "type": "string",
          "description": "The 4-letter stock code, for example: BBCA"
        }
      },
      "required": ["secCode"]
    }
    ```
-   **Output Format:** An indented JSON object with the dominant buyer/seller brokers per period (1W/1M/3M/6M), each including broker code and names, buy/sell/net values, total market value, average prices, estimated P&L percentage, and dominance percentage, plus a negotiate-market summary. A missing code yields an `{"error": "..."}` object.
-   **Logic / Algorithm:**
    1.  Unmarshals the `secCode` argument and validates it is non-empty.
    2.  Upcases the code and calls `toolutils.GetDominantBrokerAnalysis`.
    3.  Marshals the result to indented JSON.

---

## Tool: `query_user_portfolio`

> Get the user's investment portfolio: stocks, mutual funds, and investment summaries. Requires user authentication and portfolio-access permission.

-   **Purpose:** To return the authenticated user's holdings and portfolio summary (total invested, cumulative P&L, market value, and per-holding details for stocks and mutual funds).
-   **Input Arguments:** None (`noArgsSchema`).
    ```json
    { "type": "object", "properties": {} }
    ```
-   **Output Format:** An indented JSON portfolio object. When portfolio access is not granted, only a `Portfolio_Note` with instructions is returned instead of holdings. Retrieval failures yield an `{"error": "..."}` object.
-   **Logic / Algorithm:**
    1.  Checks for context cancellation before any API call.
    2.  Calls `toolutils.GetUserPortfolio` (which enforces the authentication/authorization checks).
    3.  Marshals the result to indented JSON.

---

## Tool: `query_user_memory`

> Get the user's stored long-term investment profile (risk tolerance, objectives, horizon, preferences). Does NOT return stock codes.

-   **Purpose:** To retrieve the user's saved investment profile from ArangoDB (risk tolerance/preference, objectives, horizon, volatility tolerance, loss attitude, return preference, product preference).
-   **Input Arguments:** None (`noArgsSchema`).
    ```json
    { "type": "object", "properties": {} }
    ```
-   **Output Format:** A JSON-formatted investment profile object. Returns only profile fields, never a list of stock codes.
-   **Logic / Algorithm:**
    1.  Checks for context cancellation.
    2.  Resolves the `user_id` from the request context via the auth helper (falling back to a default test user in test mode).
    3.  Queries ArangoDB for the stored profile and marshals it to JSON.

---

## Tool: `query_user_watchlist`

> Get the user's complete watchlist with all groups and their stocks. Requires user authentication.

-   **Purpose:** To return every watchlist group for the authenticated user, with group names translated to human-readable labels and per-stock metadata.
-   **Input Arguments:** None (`noArgsSchema`).
    ```json
    { "type": "object", "properties": {} }
    ```
-   **Output Format:** A structured JSON object listing group names (e.g. "All", "Group A") and, for each group, its stocks with fields such as `stock_code`, `isMutualFund`, `isTuntunPortfolioStock`, `isTuntunPortfolioMf`, and `fundGroup`.
-   **Logic / Algorithm:**
    1.  Fetches all watchlist groups for the authenticated user via `toolutils.QueryUserWatchlist` (backed by the `DataStore`).
    2.  Translates internal group codes to readable names and structures the result as JSON.

---

## Tool: `query_user_short_term_memory` (conditionally registered)

> Get the user's current short-term context: active goals, current blockers, topics of interest, and stocks they are actively following. Registered only when `EnableUserShortTermMemory` is on.

-   **Purpose:** To surface what the user is presently trying to do or struggling with, for personalization. Each item includes its mention frequency over the last 30 days and when it was last mentioned; the payload also includes the current date. This does NOT return the long-term investment profile (use `query_user_memory`).
-   **Input Arguments:** None (`noArgsSchema`).
    ```json
    { "type": "object", "properties": {} }
    ```
-   **Output Format:** A JSON object with the user's active goals, current blockers/problems, interest topics, and followed stocks — each with mention counts and last-mentioned timestamps — plus the current date.
-   **Logic / Algorithm:**
    1.  Registered only when the `EnableUserShortTermMemory` master switch is enabled.
    2.  Checks for context cancellation, then calls `toolnonbe.QueryUserShortTermMemory` (backed by ArangoDB) to assemble the short-term context.
    3.  Marshals the result to JSON.
