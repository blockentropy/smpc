"""
This script implements a server that loads a pre-split transformer model and processes client requests for inference.

Class:
------
TransformerSplitServer:
    - __init__: Initializes server with model, host, port, and device.
    - _load_model: Loads the model onto the specified device.
    - handle_client: Receives client data, runs inference, and sends the result.
    - start_server: Starts the server to listen for connections.

Usage:
------
Run with `python LlamaTransformerSplitServer.py --split_model_file_path "/path/to/model.pth" --host "0.0.0.0" --port 8765 --device "cuda"`.

"""

import socket
import pickle
import torch
import struct
import argparse
import traceback, time

# from transformers import LlamaDeco


class LlamaTransformerSplitServer:
    def __init__(self, split_model_file_path, host='0.0.0.0', port=8765, device='cuda'):
        self.host = host
        self.port = port
        self.device = device
        self.transformer_layers_split = self._load_model(split_model_file_path)
        self.transformer_layers_split.eval()
        

    def _load_model(self, split_model_file_path):
        '''
        model_path will consist of a file that holds transfomer blocks and required state dicts
        '''
        transformer_layers_split = torch.load(split_model_file_path)

        # for layer in transformer_layers_split.items():

        return transformer_layers_split.to(self.device).half()


    def handle_client(self, client_socket):

        try:
            # Receive the size of the data
            data_size = struct.unpack('>I', client_socket.recv(4))[0]

            # Now receive the data itself
            chunks = []
            bytes_recd = 0
            while bytes_recd < data_size:
                chunk = client_socket.recv(min(data_size - bytes_recd, 2048))
                if chunk == b'':
                    raise RuntimeError("socket connection broken")
                chunks.append(chunk)
                bytes_recd = bytes_recd + len(chunk)
            data = b''.join(chunks)

            input_data = pickle.loads(data)

            # Unpack the input
            with torch.no_grad():
                hidden_states, causal_mask, position_ids, past_key_values, output_attentions, use_cache, cache_position, position_embeddings = input_data

                hidden_states = hidden_states.to(self.device).half()
                # causal_mask = causal_mask.to(self.device).half()
                position_ids = position_ids.to(self.device).half()
                past_key_values = past_key_values.to(self.device).half()
                cache_position = cache_position.to(self.device).half()

            if causal_mask is not None:
                    causal_mask = causal_mask.to(self.device).half()
                
            if position_embeddings is not None:
                # position_embeddings = position_embeddings.to(self.device).half()
                position_embeddings = tuple(tensor.to(self.device).half() for tensor in position_embeddings)


                # Run the model
                for decoder_layer in self.transformer_layers_split:

                    layer_outputs = decoder_layer(
                        hidden_states,
                        attention_mask=causal_mask,
                        position_ids=position_ids,
                        past_key_value=past_key_values,
                        output_attentions=output_attentions,
                        use_cache=use_cache,
                        cache_position=cache_position,
                        position_embeddings=position_embeddings,
                    )


                    hidden_states = layer_outputs[0]

                    if use_cache:
                        next_decoder_cache = layer_outputs[2 if output_attentions else 1]


                output = (hidden_states, next_decoder_cache, past_key_values)

                

            # Send back the result
            result = pickle.dumps(output)
            result_size = len(result)
            client_socket.sendall(struct.pack('>I', result_size))
            client_socket.sendall(result)

        except Exception as e:
            print(f"Error handling client: {e}")
        
        finally:
            client_socket.close()

    def start_server(self):
        while True:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    server.bind((self.host, self.port))
                    server.listen(5)
                    print(f"Server for transformer_split listening on {self.host}:{self.port}")

                    while True:
                        client_socket, addr = server.accept()
                        print(f"Accepted connection from {addr}")
                        self.handle_client(client_socket)

            except Exception as e:
                print(f"Server error: {e}")
                print("Traceback:")
                traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description="Start the Transformer Split Server.")
    
    parser.add_argument('--host', type=str, default='0.0.0.0', help="Host IP address to bind the server (default: 0.0.0.0)")
    parser.add_argument('--port', type=int, default=8765, help="Port number to bind the server (default: 8765)")
    parser.add_argument('--device', type=str, default='cuda', help="Device to load the model onto (default: cuda)")
    parser.add_argument('--split_model_file_path', type=str, required=True, help="Path to the split transformer model file")

    args = parser.parse_args()

    # Initialize the Transformer Split Server
    server = LlamaTransformerSplitServer(
        split_model_file_path=args.split_model_file_path,
        host=args.host,
        port=args.port,
        device=args.device
    )

    # Start the server
    server.start_server()

if __name__ == "__main__":
    main()