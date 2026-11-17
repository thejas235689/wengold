// Shared DUT for the Xezim simulation and Yosys connectivity checks.
module preview_subsystem (
  input logic clk, rst_n, start, cpu, stall,
  input logic [3:0] read_addr,
  output wire ready, irq, dma, gd, gc,
  output wire [3:0] write_addr,
  output wire [7:0] write_data,
  output wire [7:0] read_data,
  output wire [3:0] dma_addr,
  output wire [7:0] dma_data
);
`ifdef MISROUTE_DMA_ADDR
  assign write_addr = gd ? (dma_addr ^ 4'd1) : 4'd2;
`else
  assign write_addr = gd ? dma_addr : 4'd2;
`endif
`ifdef CORRUPT_DMA_PAYLOAD
  assign write_data = gd ? (dma_data ^ 8'h01) : 8'hE2;
`else
  assign write_data = gd ? dma_data : 8'hE2;
`endif
  preview_dma engine(clk, rst_n, start, gd && ready, dma, irq, dma_addr, dma_data);
  preview_arbiter arb(clk, rst_n, dma, cpu, ready, gd, gc);
  preview_memory mem(clk, rst_n, gd || gc, stall, write_addr, read_addr,
                     write_data, ready, read_data);
endmodule
