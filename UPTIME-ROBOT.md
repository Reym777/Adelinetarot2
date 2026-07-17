# UptimeRobot - keepalive

Use UptimeRobot to ping the free Render instance and reduce cold starts.

## Monitor settings

- Monitor type: `HTTP(s)`
- Friendly name: `adelinemagica-health`
- URL: `https://adelinemagica.onrender.com/api/health`
- Monitoring interval: `5 minutes`
- Timeout: `30 seconds`
- HTTP method: `GET`
- Keyword monitoring: optional (`"status":"ok"`)

## Notes

- The endpoint already exists in the backend: `/api/health`.
- Render free plan can still sleep occasionally; keepalive only reduces wake-up delays.
- If your production domain is custom, use that domain instead of `onrender.com`.
