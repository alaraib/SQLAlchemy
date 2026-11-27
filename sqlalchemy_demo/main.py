from decimal import Decimal
from sqlalchemy import select
from database import engine, SessionLocal
from models import Base, Product

Base.metadata.create_all(engine)
print("Database ready")


def add_products():
    with SessionLocal() as session:
        if session.scalars(select(Product).limit(1)).first():
            return
        session.add_all([
            Product(name="Laptop", price=45000, stock=10),
            Product(name="Keyboard", price=1500, stock=25),
            Product(name="Mouse", price=500, stock=50),
            Product(name="Monitor", price=12000, stock=15),
            Product(name="Headphone", price=2000, stock=30)
        ])
        session.commit()
def list_products():
    with SessionLocal() as session:
        products = session.scalars(
            select(Product).order_by(Product.id)
        ).all()
        for p in products:
            print(p.id, p.name, p.price, p.stock)
def search_products(max_price):
    with SessionLocal() as session:
        products = session.scalars(
            select(Product).where(Product.price < max_price)
        ).all()
        for p in products:
            print(p.id, p.name, p.price)

def create_product(name, price, stock):
    with SessionLocal() as session:
        session.add(Product(name=name, price=price, stock=stock))
        session.commit()
        print("Product created")

def update_price(product_id, new_price):
    with SessionLocal() as session:
        product = session.get(Product, product_id)
        if product is None:
            print("Product not found")
            return
        product.price = new_price
        session.commit()
        print("Price updated")

def delete_product(product_id):
    with SessionLocal() as session:
        product = session.get(Product, product_id)
        if product is None:
            print("Product not found")
            return
        session.delete(product)
        session.commit()
        print("Product deleted")
def purchase_product(product_id, quantity, simulate_failure=False):
    with SessionLocal() as session:
        try:
            product = session.get(Product, product_id)
            if product is None:
                raise ValueError("Product not found")
            if quantity <= 0:
                raise ValueError("Invalid quantity")
            if product.stock < quantity:
                raise ValueError("Insufficient stock")
            product.stock -= quantity
            session.flush()
            if simulate_failure:
                raise RuntimeError("Simulated system failure")
            session.commit()
            print("Purchase successful")
        except Exception as error:
            session.rollback()
            print("Transaction failed:", error)
if __name__ == "__main__":
    add_products()
    print("\nInitial inventory")
    list_products()
    print("\nProducts below 3000")
    search_products(Decimal("3000"))
    create_product("Printer", Decimal("8000"), 12)
    update_price(2, Decimal("1200"))
    delete_product(3)
    purchase_product(1, 3)
    purchase_product(1, 20)
    purchase_product(1, 2, simulate_failure=True)
    print("\nFinal inventory")
    list_products()
