module counter4_tb;
  logic clk = 1'b0;
  logic rst_n = 1'b1;
  logic en = 1'b0;
  wire [3:0] count;
  counter4 dut(.clk(clk), .rst_n(rst_n), .en(en), .count(count));
  always #5 clk = ~clk;

  initial begin
    #2 rst_n = 1'b0;
    #1;
    if (count !== 4'd0) $fatal(1, "RESET_FAIL");
    $display("COVER:reset");

    #2 rst_n = 1'b1;
    @(negedge clk);
    en = 1'b1;
    @(posedge clk);
    #1;
    if (count !== 4'd1) $fatal(1, "INCREMENT_FAIL");
    $display("COVER:increment");

    @(negedge clk);
    en = 1'b0;
    @(posedge clk);
    #1;
    if (count !== 4'd1) $fatal(1, "HOLD_FAIL");
    $display("COVER:hold");

    // Deliberately leave wrap-around unexercised for closure example.
    $display("REGRESSION_PASS");
    $finish;
  end
  initial begin
    #300;
    $fatal(1, "TIMEOUT_FAIL");
  end
endmodule
