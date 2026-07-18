const { Pool } = require('pg');

const pool = new Pool({
  connectionString: 'postgresql://admin:password123@localhost:5432/traffic_db',
  ssl: false,
});

(async () => {
  try {
    const res = await pool.query("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name");
    console.log(JSON.stringify(res.rows, null, 2));
  } catch (err) {
    console.error(err.message);
    process.exit(1);
  } finally {
    await pool.end();
  }
})();
