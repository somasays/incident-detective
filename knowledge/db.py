"""Neo4j driver lifecycle with bounded readiness and transaction timeouts."""

import time

from neo4j import GraphDatabase, unit_of_work

from config import Settings


class Database:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        if not self.settings.neo4j_password:
            raise ValueError("Set NEO4J_PASSWORD in .env before connecting to local Neo4j.")
        self.driver = GraphDatabase.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_username, self.settings.neo4j_password),
            connection_timeout=3,
            connection_acquisition_timeout=5,
            max_transaction_retry_time=3,
            max_connection_pool_size=8,
            telemetry_disabled=True,
        )

    def read(self, cypher: str, **params) -> list[dict]:
        @unit_of_work(timeout=10)
        def work(tx):
            return tx.run(cypher, **params).data()

        with self.driver.session(database=self.settings.neo4j_database) as session:
            return session.execute_read(work)

    def write_transaction(self, work, *args):
        with self.driver.session(database=self.settings.neo4j_database) as session:
            return session.execute_write(unit_of_work(timeout=20)(work), *args)

    def write(self, cypher: str, **params):
        @unit_of_work(timeout=10)
        def work(tx):
            return tx.run(cypher, **params).data()

        with self.driver.session(database=self.settings.neo4j_database) as session:
            return session.execute_write(work)

    def wait_ready(self, attempts: int = 20, delay: float = 2):
        last_error = None
        for attempt in range(attempts):
            try:
                self.read("RETURN 1 AS ready")
                return
            except Exception as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(delay)
        raise ConnectionError(
            f"Local Neo4j not ready after {attempts} attempts. Run docker compose up -d."
        ) from last_error

    def close(self):
        self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
