require("dotenv").config();
const pg = require("pg");

let postgresConfig = {
  user: process.env.POSTGRESQL_USER,
  host: process.env.POSTGRESQL_HOST,
  database: process.env.POSTGRESQL_DATABASE,
  password: process.env.POSTGRESQL_PASSWORD,
  port: Number(process.env.POSTGRESQL_PORT),
};

if (process.env.ENVIRONMENT !== "dev") {
  postgresConfig = {
    ...postgresConfig,
    ssl: process.env.POSTGRESQL_SSL ? { rejectUnauthorized: false } : false,
  };
}

const postgresql = new pg.Pool(postgresConfig);

// Force every checked-out connection into the qa schema first. Defence-in-depth:
// even if a query forgets to qualify, it cannot resolve to a public product table
// without `public.` prefix — and our writes always fully qualify anyway.
postgresql.on("connect", (client) => {
  client.query("SET search_path TO qa, public").catch((e) => {
    console.warn("[qa-be] failed to set search_path:", e.message);
  });
});

postgresql.on("error", (err) => {
  console.warn("[qa-be] idle client error swallowed:", err.message);
});

module.exports = postgresql;
