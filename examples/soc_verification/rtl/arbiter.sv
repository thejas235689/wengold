module preview_arbiter (
  input logic clk, rst_n, dma, cpu, ready,
  output logic grant_dma, grant_cpu
);
  localparam bit CPU_FIRST = 1'b1;
  logic locked, held_dma, pick_dma;
  always_comb begin
    pick_dma = locked ? held_dma : dma && (!cpu || !CPU_FIRST);
    grant_dma = pick_dma && dma;
    grant_cpu = !pick_dma && cpu;
  end
  always @(posedge clk) begin
    if (!rst_n) begin
      locked <= 0;
      held_dma <= 0;
    end else begin
      locked <= !ready && (grant_dma || grant_cpu);
      held_dma <= grant_dma;
    end
  end
endmodule
