module.exports = {
  apps: [
    {
      name: "tural-tiktok-scraper",
      script: "main.py",
      interpreter: "/root/apps/tural-tiktok-scraper/.venv/bin/python",
      cwd: "/root/apps/tural-tiktok-scraper",
      env: {
        NODE_ENV: "production",
      },
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: "1G",
      error_file: "./logs/err.log",
      out_file: "./logs/out.log",
      log_file: "./logs/combined.log",
      time: true,
    },
  ],
};
