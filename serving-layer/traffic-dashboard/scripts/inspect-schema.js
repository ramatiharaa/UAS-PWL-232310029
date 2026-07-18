const { Pool } = require('pg');

const pool = new Pool({
  connectionString: 'postgresql://admin:password123@localhost:5432/traffic_db',
  ssl: false,
});

(async () => {
  try {
    const columns = await pool.query(
      "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' AND (table_name = 'camera_summary_simple' OR table_name = 'rep_traffic_summary_5min' OR table_name = 'rep_traffic_summary_5min_by_type') ORDER BY table_name, ordinal_position"
    );

    console.log('Columns:');
    for (const row of columns.rows) {
      console.log(`${row.table_name}: ${row.column_name}`);
    }

    const viewSample = await pool.query('SELECT * FROM public.camera_summary_simple LIMIT 5');
    const historySample = await pool.query('SELECT * FROM public.rep_traffic_summary_5min LIMIT 5');
    const typeSample = await pool.query('SELECT * FROM public.rep_traffic_summary_5min_by_type LIMIT 5');

    console.log('\ncamera_summary_simple sample:');
    console.log(JSON.stringify(viewSample.rows, null, 2));
    console.log('\nrep_traffic_summary_5min sample:');
    console.log(JSON.stringify(historySample.rows, null, 2));
    console.log('\nrep_traffic_summary_5min_by_type sample:');
    console.log(JSON.stringify(typeSample.rows, null, 2));
  } catch (err) {
    console.error(err.message);
    process.exit(1);
  } finally {
    await pool.end();
  }
})();
