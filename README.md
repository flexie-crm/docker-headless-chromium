# Docker Headless Chromium Controller

## Overview

This repository provides a Dockerized service for running Headless Chromium with a persistent WebSocket connection, allowing efficient PDF rendering, web scraping, and other Chromium-based tasks. Unlike typical implementations that start and stop a new browser instance for each request, this service maintains a persistent connection to avoid initialization overhead.

## Features

- **Efficient PDF Generation**: Keeps Chromium running to avoid cold start delays.
- **WebSocket Proxy**: Routes connections to the Chromium DevTools Protocol.
- **Web Scraping & Screenshots**: Supports additional tasks beyond PDF rendering.
- **Graceful Shutdown**: Manages Chromium process lifecycle.
- **Customizable**: Configure Chromium startup options via environment variables.

## Getting Started

### Prerequisites

- Docker installed on your system

### Installation & Running the Service

To start the service using Docker, run:

```sh
# Clone the repository
git clone https://github.com/flexie-crm/docker-headless-chromium.git
cd docker-headless-chromium

# Build the Docker image
docker build -t headless-chromium .

# Run the container
docker run -d --name chromium-container -p 9222:9222 headless-chromium
```

### Verifying the Service

After running the container, verify that the service is working by visiting:

```
http://localhost:9222/json/version
```

You should see JSON output indicating that Headless Chromium is running.

## Usage

The service exposes a WebSocket debugging protocol at `ws://{container_name}:9222/devtools/browser`.

### Using Chrome-PHP (PHP)

```php
use HeadlessChromium\BrowserFactory;

$browser = BrowserFactory::connectToBrowser('ws://chromium-container:9222/devtools/browser');
$page = $browser->createPage();

// Set the HTML content
$page->setHtml('<html><body><h1>Hello, World!</h1></body></html>');

// Generate PDF
$pdf = $page->pdf([ 'format' => 'A4' ])->getRawBinary();

$page->close();
$browser->getConnection()->disconnect();
```

### Using Puppeteer (Node.js)

```javascript
const puppeteer = require('puppeteer-core');

(async () => {
    const browser = await puppeteer.connect({
        browserWSEndpoint: 'ws://chromium-container:9222/devtools/browser'
    });
    const page = await browser.newPage();
    await page.setContent('<html><body><h1>Hello, World!</h1></body></html>');
    
    // Generate PDF
    await page.pdf({ path: 'output.pdf', format: 'A4' });

    await browser.close();
})();
```

### Using Python with WebSocket Client

```python
import asyncio
import websockets
import json

async def main():
    async with websockets.connect('ws://chromium-container:9222/devtools/browser') as ws:
        await ws.send(json.dumps({
            "id": 1,
            "method": "Page.printToPDF",
            "params": {"landscape": False, "format": "A4"}
        }))
        response = await ws.recv()
        print(response)

asyncio.run(main())
```

### Using Go with WebSocket Connection

```go
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/gorilla/websocket"
	"os"
)

type PDFRequest struct {
	ID     int               `json:"id"`
	Method string            `json:"method"`
	Params map[string]interface{} `json:"params"`
}

type PDFResponse struct {
	Data string `json:"data"`
}

func main() {
	wsURL := "ws://chromium-container:9222/devtools/browser"
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		panic(fmt.Errorf("failed to connect to websocket: %w", err))
	}
	defer conn.Close()

	request := PDFRequest{
		ID:     1,
		Method: "Page.printToPDF",
		Params: map[string]interface{}{
			"landscape": false,
			"format": "A4",
		},
	}

	if err := conn.WriteJSON(request); err != nil {
		panic(fmt.Errorf("failed to send request: %w", err))
	}

	var response PDFResponse
	if err := conn.ReadJSON(&response); err != nil {
		panic(fmt.Errorf("failed to read response: %w", err))
	}

	pdfData, err := os.Create("output.pdf")
	if err != nil {
		panic(fmt.Errorf("failed to create PDF file: %w", err))
	}
	defer pdfData.Close()

	_, err = pdfData.Write([]byte(response.Data))
	if err != nil {
		panic(fmt.Errorf("failed to write PDF data: %w", err))
	}
}
```

## Configuration

You can configure the browser by passing environment variables:

| Variable              | Description                                  | Default Value |
| --------------------- | -------------------------------------------- | ------------- |
| `CHROME_DEBUG_HOST`   | Chromium Debugging Host                      | `127.0.0.1`   |
| `CHROME_DEBUG_PORT`   | Chromium Debugging Port                      | `9223`        |
| `PROXY_LISTEN_HOST`   | Proxy WebSocket Host                         | `0.0.0.0`     |
| `PROXY_LISTEN_PORT`   | Proxy WebSocket Port                         | `9222`        |
| `CHROMIUM_EXECUTABLE` | Chromium Executable Path                     | `chromium`    |
| `RETRY_ATTEMPTS`      | Browser ID Fetch Retry Attempts              | `10`          |
| `INITIAL_RETRY_DELAY` | Initial delay for retrying connection        | `1.0` seconds |
| `MAX_RETRY_DELAY`     | Maximum delay for retrying connection        | `30.0` seconds|
| `CONNECT_TIMEOUT`     | Timeout for establishing WebSocket connection| `10.0` seconds|
| `CLOSE_TIMEOUT`       | Timeout for closing WebSocket connection     | `2.0` seconds |

## Troubleshooting

### Error: `Connection Refused`

- Ensure the container is running with `docker ps`
- Check if the port is correctly mapped with `docker logs <container_id>`

### Error: `Timeout while connecting`

- Increase the timeout in your client library (e.g., in Puppeteer, set `{timeout: 60000}`)

## Contributing

Feel free to open an issue or submit a pull request if you have improvements or bug fixes.

## License

This project is licensed under the MIT License.