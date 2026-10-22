// A counter that wraps at MAX — provable.
module counter (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       en
);
    parameter int MAX = 4;
    logic [2:0] count;

    always_ff @(posedge clk) begin
        if (!rst_n)      count <= 0;
        else if (en)     count <= (count == MAX) ? 0 : count + 1;
    end
endmodule
