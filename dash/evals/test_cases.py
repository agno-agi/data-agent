"""
Test cases for evaluating Dash against TPC-H data.

Each test case includes:
- question: The natural language question to ask
- expected_strings: Strings that should appear in the response (for backward compatibility)
- category: Test category for filtering
- golden_sql: Optional SQL query that produces the expected result

When golden_sql is provided, the evaluation will:
1. Execute the golden SQL to get expected results
2. Compare against actual query results from the agent's response
"""

from dataclasses import dataclass


@dataclass
class TestCase:
    """A test case for evaluating Dash."""

    question: str
    expected_strings: list[str]
    category: str
    golden_sql: str | None = None
    # Expected result for simple queries (e.g., a count or single value)
    expected_result: str | None = None


# Test cases organized by category
TEST_CASES: list[TestCase] = [
    # =========================================================================
    # Basic - straightforward single-table queries
    # =========================================================================
    TestCase(
        question="How many customers are in the database?",
        expected_strings=["150"],
        category="basic",
        golden_sql="SELECT COUNT(*) as customer_count FROM customer",
        expected_result="150000",
    ),
    TestCase(
        question="How many orders are there in total?",
        expected_strings=["1,500,000"],
        category="basic",
        golden_sql="SELECT COUNT(*) as order_count FROM orders",
        expected_result="1500000",
    ),
    TestCase(
        question="What are the five regions in the database?",
        expected_strings=["AFRICA", "AMERICA", "ASIA", "EUROPE", "MIDDLE EAST"],
        category="basic",
        golden_sql="SELECT r_name FROM region ORDER BY r_name",
    ),
    TestCase(
        question="What are the different customer market segments?",
        expected_strings=["AUTOMOBILE", "BUILDING", "FURNITURE", "HOUSEHOLD", "MACHINERY"],
        category="basic",
        golden_sql="SELECT DISTINCT c_mktsegment FROM customer ORDER BY 1",
    ),
    # =========================================================================
    # Aggregation - GROUP BY, ranking queries
    # =========================================================================
    TestCase(
        question="Which nation has the highest total order revenue?",
        expected_strings=["FRANCE"],
        category="aggregation",
        golden_sql="""
            SELECT n.n_name, ROUND(SUM(o.o_totalprice)::NUMERIC, 2) as revenue
            FROM orders o
            JOIN customer c ON o.o_custkey = c.c_custkey
            JOIN nation n ON c.c_nationkey = n.n_nationkey
            GROUP BY n.n_name
            ORDER BY revenue DESC
            LIMIT 1
        """,
    ),
    TestCase(
        question="Which market segment generates the most revenue?",
        expected_strings=["BUILDING"],
        category="aggregation",
        golden_sql="""
            SELECT c.c_mktsegment, ROUND(SUM(o.o_totalprice)::NUMERIC, 2) as revenue
            FROM orders o
            JOIN customer c ON o.o_custkey = c.c_custkey
            GROUP BY c.c_mktsegment
            ORDER BY revenue DESC
            LIMIT 1
        """,
    ),
    TestCase(
        question="Which order priority has the most orders?",
        expected_strings=["5-LOW"],
        category="aggregation",
        golden_sql="""
            SELECT o_orderpriority, COUNT(*) as cnt
            FROM orders
            GROUP BY o_orderpriority
            ORDER BY cnt DESC
            LIMIT 1
        """,
    ),
    TestCase(
        question="Which nation has the most suppliers?",
        expected_strings=["IRAQ"],
        category="aggregation",
        golden_sql="""
            SELECT n.n_name, COUNT(*) as supplier_count
            FROM supplier s
            JOIN nation n ON s.s_nationkey = n.n_nationkey
            GROUP BY n.n_name
            ORDER BY supplier_count DESC
            LIMIT 1
        """,
    ),
    TestCase(
        question="Which part brand has the highest total revenue?",
        expected_strings=["Brand#35"],
        category="aggregation",
        golden_sql="""
            SELECT p.p_brand,
                   ROUND(SUM(l.l_extendedprice * (1 - l.l_discount))::NUMERIC, 2) as revenue
            FROM lineitem l
            JOIN part p ON l.l_partkey = p.p_partkey
            GROUP BY p.p_brand
            ORDER BY revenue DESC
            LIMIT 1
        """,
    ),
    # =========================================================================
    # Data quality - tests column naming, type handling, date filtering
    # =========================================================================
    TestCase(
        question="How many orders were placed in 1995?",
        expected_strings=["228"],
        category="data_quality",
        golden_sql="""
            SELECT COUNT(*) as order_count
            FROM orders
            WHERE o_orderdate >= '1995-01-01'
              AND o_orderdate < '1996-01-01'
        """,
        expected_result="228637",
    ),
    TestCase(
        question="What percentage of orders are marked as urgent?",
        expected_strings=["20"],
        category="data_quality",
        golden_sql="""
            SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE o_orderpriority = '1-URGENT') / COUNT(*), 1) as pct
            FROM orders
        """,
        expected_result="20.0",
    ),
    TestCase(
        question="How many line items have been returned?",
        expected_strings=["1,478,870"],
        category="data_quality",
        golden_sql="""
            SELECT COUNT(*) as returned_count
            FROM lineitem
            WHERE l_returnflag = 'R'
        """,
        expected_result="1478870",
    ),
    TestCase(
        question="What are the possible order statuses and how many orders are in each?",
        expected_strings=["F", "O", "P"],
        category="data_quality",
        golden_sql="""
            SELECT o_orderstatus, COUNT(*) as cnt
            FROM orders
            GROUP BY o_orderstatus
            ORDER BY cnt DESC
        """,
    ),
    # =========================================================================
    # Complex - multi-table JOINs, subqueries, comparisons
    # =========================================================================
    TestCase(
        question="Compare total order revenue across all five regions",
        expected_strings=["EUROPE", "ASIA", "AMERICA", "AFRICA", "MIDDLE EAST"],
        category="complex",
        golden_sql="""
            SELECT r.r_name, ROUND(SUM(o.o_totalprice)::NUMERIC, 2) as revenue
            FROM orders o
            JOIN customer c ON o.o_custkey = c.c_custkey
            JOIN nation n ON c.c_nationkey = n.n_nationkey
            JOIN region r ON n.n_regionkey = r.r_regionkey
            GROUP BY r.r_name
            ORDER BY revenue DESC
        """,
    ),
    TestCase(
        question="What are the top 3 nations by number of suppliers and how many does each have?",
        expected_strings=["IRAQ", "PERU", "ALGERIA"],
        category="complex",
        golden_sql="""
            SELECT n.n_name, COUNT(*) as supplier_count
            FROM supplier s
            JOIN nation n ON s.s_nationkey = n.n_nationkey
            GROUP BY n.n_name
            ORDER BY supplier_count DESC
            LIMIT 3
        """,
    ),
    TestCase(
        question="Which ship mode is used most frequently?",
        expected_strings=["TRUCK", "SHIP", "AIR"],
        category="complex",
        golden_sql="""
            SELECT l_shipmode, COUNT(*) as cnt
            FROM lineitem
            GROUP BY l_shipmode
            ORDER BY cnt DESC
        """,
    ),
    # =========================================================================
    # Edge cases - boundary conditions, tricky questions
    # =========================================================================
    TestCase(
        question="Which customer has the highest account balance and what nation are they from?",
        expected_strings=["Customer#000061453", "MOROCCO"],
        category="edge_case",
        golden_sql="""
            SELECT c.c_name, c.c_acctbal, n.n_name
            FROM customer c
            JOIN nation n ON c.c_nationkey = n.n_nationkey
            ORDER BY c.c_acctbal DESC
            LIMIT 1
        """,
    ),
    TestCase(
        question="Are there any customers with a negative account balance? How many?",
        expected_strings=[],
        category="edge_case",
        golden_sql="""
            SELECT COUNT(*) as negative_balance_count
            FROM customer
            WHERE c_acctbal < 0
        """,
    ),
]

# Categories for filtering
CATEGORIES = ["basic", "aggregation", "data_quality", "complex", "edge_case"]


# Backward compatibility: export as tuples for any code expecting the old format
def get_legacy_test_cases() -> list[tuple[str, list[str], str]]:
    """Get test cases in legacy tuple format (question, expected_strings, category)."""
    return [(tc.question, tc.expected_strings, tc.category) for tc in TEST_CASES]
