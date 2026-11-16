// Compiled without the DMA, arbiter or their subsystem testbench.
module memory_tb;
  logic clk = 0, rst_n = 0, valid = 0;
  logic ready;
  logic [7:0] value;
  preview_memory mem(clk, rst_n, valid, 1'b0, 4'd2, 4'd2, 8'h5A, ready, value);
  always #5 clk = ~clk;
  initial begin
    @(negedge clk);
    if (value !== 8'h00) $fatal(1, "FAIL:REQ-MEMORY:0");
    rst_n = 1;
    valid = 1;
    @(negedge clk);
    if (value !== 8'h5A) $fatal(1, "FAIL:REQ-MEMORY:1");
    $display("HIT:REQ-MEMORY");
    $display("SOC_PREVIEW_PASS");
    $finish;
  end
endmodule
