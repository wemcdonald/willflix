#!/usr/bin/env python3

import json
import subprocess
import logging
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [WEBHOOK] %(message)s',
    handlers=[
        logging.FileHandler('/app/logs/webhook.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

class WebhookHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Use our custom logger instead of default
        logging.info(f"{self.address_string()} - {format % args}")
    
    def do_GET(self):
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')
    
    def do_POST(self):
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/webhook/user-sync':
            try:
                # Read request body
                content_length = int(self.headers.get('Content-Length', 0))
                request_body = self.rfile.read(content_length).decode('utf-8')
                
                logging.info(f"Received webhook payload: {request_body}")
                
                # Parse JSON
                webhook_data = json.loads(request_body)
                
                event_type = webhook_data.get('event', '')
                user_data = webhook_data.get('user', {})
                username = user_data.get('username', '')
                email = user_data.get('email', '')
                
                logging.info(f"Event: {event_type}, User: {username}, Email: {email}")
                
                if event_type == 'user.created' and username and email:
                    logging.info(f"Processing user creation for: {username} ({email})")
                    
                    # Call sync-users script
                    try:
                        result = subprocess.run(
                            ['/app/bin/sync-users', username],
                            capture_output=True,
                            text=True,
                            timeout=300  # 5 minute timeout
                        )
                        
                        if result.returncode == 0:
                            logging.info(f"Successfully synced user: {username}")
                            response = {"status": "success", "message": f"User {username} synced successfully"}
                        else:
                            logging.error(f"Failed to sync user {username}: {result.stderr}")
                            response = {"status": "error", "message": f"Sync failed: {result.stderr}"}
                    
                    except subprocess.TimeoutExpired:
                        logging.error(f"Timeout syncing user: {username}")
                        response = {"status": "error", "message": "Sync timeout"}
                    except Exception as e:
                        logging.error(f"Exception syncing user {username}: {str(e)}")
                        response = {"status": "error", "message": str(e)}
                else:
                    logging.info("Ignoring webhook (not user.created or missing data)")
                    response = {"status": "ignored", "message": "Not a user creation event"}
                
                # Send response
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode('utf-8'))
                
            except json.JSONDecodeError as e:
                logging.error(f"Invalid JSON in webhook: {str(e)}")
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error":"invalid json"}')
            
            except Exception as e:
                logging.error(f"Webhook processing error: {str(e)}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error":"internal error"}')
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')

def run_server(port=8080):
    server_address = ('', port)
    httpd = HTTPServer(server_address, WebhookHandler)
    logging.info(f"Starting webhook server on port {port}")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logging.info("Shutting down webhook server")
        httpd.shutdown()

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    
    # Ensure log directory exists
    os.makedirs('/app/logs', exist_ok=True)
    
    run_server(port)