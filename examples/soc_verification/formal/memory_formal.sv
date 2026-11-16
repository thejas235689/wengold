module memory_formal (
  input logic clk, rst_n, valid, stall,
  input logic [3:0] addr,
  input logic [7:0] data
);
  (* anyconst *) logic [3:0] watch_addr;
  wire ready;
  wire [7:0] read_data;
  preview_memory dut(clk, rst_n, valid, stall, addr, watch_addr, data, ready, read_data);

  logic past_valid = 0;
  logic [7:0] expected = 0;
  always @(posedge clk) begin
    past_valid <= 1;
    if (!past_valid) assume (!rst_n);
    if (past_valid) begin
      ready_matches_stall: assert (ready == !stall);
      watched_word_matches_model: assert (read_data == expected);
      accepted_write_to_watched_word: cover (
        rst_n && valid && !stall && addr == watch_addr && data != 0
      );
      reset_after_nonzero_write: cover (!rst_n && expected != 0);
    end
    if (!rst_n) expected <= 0;
    else if (valid && !stall && addr == watch_addr) expected <= data;
  end
endmodule
