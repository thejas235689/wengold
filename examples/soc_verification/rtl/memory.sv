module preview_memory (
  input logic clk, rst_n, valid, stall,
  input logic [3:0] addr, read_addr,
  input logic [7:0] data,
  output logic ready,
  output logic [7:0] read_data
);
  logic [7:0] mem [0:15];
  assign ready = !stall;
  assign read_data = mem[read_addr];
  always @(posedge clk) begin
    if (!rst_n) begin
      for (int i = 0; i < 16; i++) mem[i] <= 0;
    end else if (valid && ready) begin
`ifdef DROP_WRITE
      if (addr != 4'd5) mem[addr] <= data;
`else
      mem[addr] <= data;
`endif
    end
  end
endmodule
