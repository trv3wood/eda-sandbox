module stream_accel(
  input  logic        clk,
  input  logic        reset_n,
  input  logic        start,
  input  logic [7:0]  length,
  input  logic [15:0] scale,
  input  logic [15:0] bias,
  input  logic        in_valid,
  output logic        in_ready,
  input  logic [15:0] in_data,
  output logic        out_valid,
  input  logic        out_ready,
  output logic [31:0] result
);
  logic active;
  logic [7:0] remaining;
  logic [31:0] accumulator;

  assign in_ready = active && !out_valid;
  assign result = accumulator;

  always_ff @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
      active <= 1'b0;
      remaining <= '0;
      accumulator <= '0;
      out_valid <= 1'b0;
    end else begin
      if (out_valid && out_ready) begin
        out_valid <= 1'b0;
        active <= 1'b0;
      end
      if (start && !active) begin
        active <= 1'b1;
        remaining <= length;
        accumulator <= '0;
      end else if (in_valid && in_ready) begin
        accumulator <= accumulator + in_data * scale + {16'd0, bias};
        remaining <= remaining - 8'd1;
        if (remaining == 8'd1)
          out_valid <= 1'b1;
      end
    end
  end
endmodule
