module preview_dma (
  input logic clk, rst_n, start, ready,
  output logic valid, irq,
  output logic [3:0] addr,
  output logic [7:0] data
);
  logic second;
  assign addr = second ? 4'd5 : 4'd4;
  assign data = second ? 8'hA7 : 8'h39;
  always @(posedge clk) begin
    if (!rst_n) begin
      valid <= 0;
      second <= 0;
      irq <= 0;
    end else begin
      irq <= 0;
      if (start && !valid) begin
        valid <= 1;
        second <= 0;
      end else if (valid && ready) begin
        if (second) begin
          valid <= 0;
          irq <= 1;
        end else begin
          second <= 1;
`ifdef EARLY_IRQ
          irq <= 1;
`endif
        end
      end
    end
  end
endmodule
