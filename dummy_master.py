import socket
import time

def run_dummy_master():
    HOST = '127.0.0.1'
    PORT = 8080
    
    print(f"Connecting to PicoScope App at {HOST}:{PORT}...")
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.connect((HOST, PORT))
            print("Connected successfully!")
            
            # Format: START,SN1,SN2,SN3,MODE_PIN1,MODE_PIN2
            # Fixed 6 parts separated by commas
            # 3 products always share the same test mode
            # Example: SENT on Pin 1, SPC on Pin 2
            cmd_str = "START,PROD-1001,PROD-1002,PROD-1003,SENT,SPC/1/3"
            
            print(f"Sending Command: {cmd_str}")
            s.sendall(f"{cmd_str}\n".encode('utf-8'))
            
            print("Waiting for test results...")
            data = s.recv(4096)
            
            print("=== Result Received ===")
            print(data.decode('utf-8').strip())
            print("=======================")
            
        except Exception as e:
            print(f"Connection failed: {e}")

if __name__ == "__main__":
    run_dummy_master()
