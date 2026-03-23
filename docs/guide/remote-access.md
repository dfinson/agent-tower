# Remote Access

CodePlane can be accessed from any device — including your phone — via Dev Tunnels, Microsoft's secure tunneling service.

## Enabling Remote Access

Start the server with the `--remote` flag:

```bash
uv run cpl up --remote
```

Or with a password:

```bash
uv run cpl up --remote --password your-secret
```

Or use `make run` which enables remote access by default.

The server will print a tunnel URL like:

```
https://abc123.devtunnels.ms
```

Open this URL on any device to access the CodePlane UI.

## Security

| Feature | Details |
|---------|---------|
| **HTTPS** | All tunnel traffic is encrypted end-to-end |
| **Password protection** | Set `CPL_TUNNEL_PASSWORD` or use `--password` |
| **Localhost trust** | Direct access on `localhost` requires no password |

!!! warning "Without a Password"
    If you don't set a password, anyone with the tunnel URL can access CodePlane. Always set a password when using remote access on shared networks.

## Mobile Experience

The UI is fully responsive. On mobile devices:

<div class="screenshot-mobile" markdown>
![Mobile Dashboard](../images/screenshots/mobile/mobile-dashboard.png)
</div>

- **Dashboard** switches to a tab-based list view
- **Terminal** drawer maximizes to full screen
- **Forms** use compact layouts
- **Voice input** works via the mobile browser's microphone API

## Use Cases

- **Monitor from your phone** — Watch jobs run while away from your desk
- **Approve actions** — Handle approval requests from anywhere
- **Quick interventions** — Cancel or send messages to running agents
- **Demo** — Share the URL to show CodePlane in action
