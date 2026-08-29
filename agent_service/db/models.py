from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from db.database import Base


class Category(Base):
    """Spending/income category with a display colour."""

    __tablename__ = "category"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    name      = Column(String(100), nullable=False, unique=True)
    type      = Column(String(20), nullable=False)   # expense | income | transfer
    color_hex = Column(String(7), nullable=False)

    def __repr__(self) -> str:
        """Show category id, name, and type."""
        return f"<Category id={self.id} name={self.name!r} type={self.type!r}>"


class Merchant(Base):
    """Merchant memory table — maps raw description to a category."""

    __tablename__ = "merchant"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    raw_name    = Column(String(255), nullable=False, unique=True)
    clean_name  = Column(String(255))
    category_id = Column(Integer, ForeignKey("category.id"))
    match_type  = Column(String(10))   # keyword | llm | manual

    def __repr__(self) -> str:
        """Show merchant id and raw name."""
        return f"<Merchant id={self.id} raw_name={self.raw_name!r} match_type={self.match_type!r}>"


class KeywordRule(Base):
    """Keyword → category mapping used before falling back to the LLM."""

    __tablename__ = "keyword_rule"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    keyword     = Column(String(100), nullable=False, unique=True)
    category_id = Column(Integer, ForeignKey("category.id"), nullable=False)
    priority    = Column(Integer, default=0)

    def __repr__(self) -> str:
        """Show keyword rule id and keyword."""
        return f"<KeywordRule id={self.id} keyword={self.keyword!r} priority={self.priority}>"


class BankStatement(Base):
    """One imported bank statement — unique per calendar month/year."""

    __tablename__ = "bank_statement"
    __table_args__ = (UniqueConstraint("statement_month", "statement_year"),)

    id               = Column(Integer, primary_key=True, autoincrement=True)
    bank_name        = Column(String(50), default="FNB")
    account_number   = Column(String(50))
    statement_month  = Column(Integer, nullable=False)
    statement_year   = Column(Integer, nullable=False)
    opening_balance  = Column(Float)
    closing_balance  = Column(Float)
    imported_at      = Column(String(30), nullable=False)

    def __repr__(self) -> str:
        """Show statement id, month, and year."""
        return (
            f"<BankStatement id={self.id} "
            f"month={self.statement_month} year={self.statement_year}>"
        )


class Transaction(Base):
    """Single line item from a bank statement."""

    __tablename__ = "transaction"

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    statement_id          = Column(Integer, ForeignKey("bank_statement.id"), nullable=False)
    transaction_date      = Column(String(10), nullable=False)   # YYYY-MM-DD
    raw_description       = Column(Text, nullable=False)
    service_fee           = Column(Float, default=0)
    # Amount is always POSITIVE; direction carries the sign. Storing signed
    # amounts would make every SUM() depend on getting the sign right upstream.
    amount                = Column(Float, nullable=False)
    direction             = Column(String(2), nullable=False)     # DR = out, CR = in
    balance               = Column(Float)
    category_id           = Column(Integer, ForeignKey("category.id"))
    merchant_id           = Column(Integer, ForeignKey("merchant.id"))
    # How the category was decided, and how much to trust it:
    #   keyword -> merchant memory or a keyword rule matched (trusted)
    #   llm     -> Gemini guessed (trusted only above the confidence threshold)
    #   user    -> a human corrected it in the review panel (always trusted)
    categorization_method = Column(String(10))
    # 0 puts the row in the review queue. Only user_confirmed=1 rows are written
    # back to merchant memory, so an unreviewed guess never becomes a fact.
    user_confirmed        = Column(Integer, default=0)
    llm_confidence        = Column(Float)   # NULL unless categorization_method="llm"

    def __repr__(self) -> str:
        """Show transaction id, date, direction, and amount."""
        return (
            f"<Transaction id={self.id} date={self.transaction_date!r} "
            f"direction={self.direction!r} amount={self.amount}>"
        )


class MonthlySummary(Base):
    """Aggregated spending per category per month — rebuilt after each import."""

    __tablename__ = "monthly_summary"
    __table_args__ = (UniqueConstraint("statement_year", "statement_month", "category_id"),)

    id                = Column(Integer, primary_key=True, autoincrement=True)
    statement_year    = Column(Integer, nullable=False)
    statement_month   = Column(Integer, nullable=False)
    category_id       = Column(Integer, ForeignKey("category.id"), nullable=False)
    total_spent       = Column(Float, default=0)
    transaction_count = Column(Integer, default=0)
    avg_transaction   = Column(Float, default=0)

    def __repr__(self) -> str:
        """Show summary id, year, month, and total spent."""
        return (
            f"<MonthlySummary id={self.id} "
            f"year={self.statement_year} month={self.statement_month} "
            f"total_spent={self.total_spent}>"
        )
